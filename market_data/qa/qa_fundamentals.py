"""QA checks for silver fundamentals tables."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.schema_registry import FUNDAMENTALS_REPORTED_PK
from market_data.common.settings import IngestionSettings

log = get_logger("qa.fundamentals")


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    asof_dir = silver_path("fundamentals_asof_daily", settings)
    if asof_dir.exists():
        asof = read_parquet(asof_dir).collect()
        stats["asof_rows"] = len(asof)

        leaky = asof.filter(
            pl.col("accepted_at").is_not_null()
            & (pl.col("trade_date") < pl.col("accepted_at").dt.date())
        )
        if len(leaky) > 0:
            errors.append(
                f"fundamentals_asof_daily: {len(leaky)} rows used before accepted_at"
            )
        stats["asof_use_before_accepted"] = len(leaky)
    else:
        warnings.append("fundamentals_asof_daily directory not found")

    reported_dir = silver_path("fundamentals_reported", settings)
    if reported_dir.exists():
        reported = read_parquet(reported_dir).collect()
        stats["reported_rows"] = len(reported)

        dup_count = len(reported) - len(
            reported.unique(subset=FUNDAMENTALS_REPORTED_PK)
        )
        if dup_count > 0:
            errors.append(
                f"fundamentals_reported: {dup_count} duplicate PK rows"
            )
        stats["reported_pk_dupes"] = dup_count
    else:
        warnings.append("fundamentals_reported directory not found")

    log.info("qa_fundamentals: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
