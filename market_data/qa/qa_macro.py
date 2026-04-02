"""QA checks for silver macro tables."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("qa.macro")


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    asof_dir = silver_path("macro_asof_daily", settings)
    vintage_dir = silver_path("macro_observations_vintage", settings)

    if not asof_dir.exists():
        warnings.append("macro_asof_daily directory not found")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    asof = read_parquet(asof_dir).collect()
    stats["asof_rows"] = len(asof)
    stats["series_count"] = asof["series_id"].n_unique()

    if vintage_dir.exists():
        vintage = read_parquet(vintage_dir).collect()
        vintage_keys = vintage.select(
            "series_id",
            "observation_date",
            pl.col("vintage_date").alias("selected_vintage_date"),
        ).unique()

        orphan = asof.join(
            vintage_keys,
            on=["series_id", "observation_date", "selected_vintage_date"],
            how="anti",
        )
        if len(orphan) > 0:
            warnings.append(
                f"{len(orphan)} asof rows with no matching vintage upstream"
            )
        stats["orphan_asof_rows"] = len(orphan)
    else:
        warnings.append(
            "macro_observations_vintage not found; skipping vintage check"
        )

    future_vintage = asof.filter(pl.col("selected_vintage_date") > pl.col("asof_date"))
    if len(future_vintage) > 0:
        errors.append(
            f"{len(future_vintage)} rows with selected_vintage_date > asof_date (future leakage)"
        )
    stats["future_vintage_leakage"] = len(future_vintage)

    asof_cutoff = (
        pl.col("asof_date").cast(pl.Datetime("us", "UTC"))
        + pl.duration(days=1)
        - pl.duration(microseconds=1)
    )
    future_available = asof.filter(pl.col("selected_available_from_ts_utc") > asof_cutoff)
    if len(future_available) > 0:
        errors.append(
            f"{len(future_available)} rows with selected_available_from_ts_utc after asof_date cutoff"
        )
    stats["future_available_leakage"] = len(future_available)

    log.info("qa_macro: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
