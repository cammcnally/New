"""QA checks for silver macro tables."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("qa.macro")


def check(
    *,
    settings: IngestionSettings,
    asof_lf: pl.LazyFrame | None = None,
    vintage_lf: pl.LazyFrame | None = None,
) -> dict:
    """Run macro PIT QA checks.

    When *asof_lf* / *vintage_lf* are provided, reuse those lazy frames instead of
    scanning the lake again (callers should not also load the same paths eagerly).
    """
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    asof_dir = silver_path("macro_asof_daily", settings)
    vintage_dir = silver_path("macro_observations_vintage", settings)

    if not asof_dir.exists():
        warnings.append("macro_asof_daily directory not found")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    asof_src = asof_lf if asof_lf is not None else read_parquet(asof_dir)
    stats["asof_rows"] = asof_src.select(pl.len()).collect().item()
    stats["series_count"] = asof_src.select(pl.col("series_id").n_unique()).collect().item()

    if vintage_lf is not None:
        vint_src = vintage_lf
        vintage_keys = vint_src.select(
            "series_id",
            "observation_date",
            pl.col("vintage_date").alias("selected_vintage_date"),
        ).unique()
        orphan = asof_src.join(
            vintage_keys,
            on=["series_id", "observation_date", "selected_vintage_date"],
            how="anti",
        )
        ocount = orphan.select(pl.len()).collect().item()
        if ocount > 0:
            warnings.append(f"{ocount} asof rows with no matching vintage upstream")
        stats["orphan_asof_rows"] = ocount
    elif vintage_dir.exists():
        vint_src = read_parquet(vintage_dir)
        vintage_keys = vint_src.select(
            "series_id",
            "observation_date",
            pl.col("vintage_date").alias("selected_vintage_date"),
        ).unique()
        orphan = asof_src.join(
            vintage_keys,
            on=["series_id", "observation_date", "selected_vintage_date"],
            how="anti",
        )
        ocount = orphan.select(pl.len()).collect().item()
        if ocount > 0:
            warnings.append(f"{ocount} asof rows with no matching vintage upstream")
        stats["orphan_asof_rows"] = ocount
    else:
        warnings.append(
            "macro_observations_vintage not found; skipping vintage check"
        )

    future_vintage = asof_src.filter(pl.col("selected_vintage_date") > pl.col("asof_date"))
    fv = future_vintage.select(pl.len()).collect().item()
    if fv > 0:
        errors.append(f"{fv} rows with selected_vintage_date > asof_date (future leakage)")
    stats["future_vintage_leakage"] = fv

    asof_cutoff = (
        pl.col("asof_date").cast(pl.Datetime("us", "UTC"))
        + pl.duration(days=1)
        - pl.duration(microseconds=1)
    )
    future_available = asof_src.filter(pl.col("selected_available_from_ts_utc") > asof_cutoff)
    fa = future_available.select(pl.len()).collect().item()
    if fa > 0:
        errors.append(
            f"{fa} rows with selected_available_from_ts_utc after asof_date cutoff"
        )
    stats["future_available_leakage"] = fa

    log.info("qa_macro: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
