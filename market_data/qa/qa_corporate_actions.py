"""QA checks for silver corporate_actions table."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.schema_registry import CORPORATE_ACTIONS_PK
from market_data.common.settings import IngestionSettings

log = get_logger("qa.corporate_actions")


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    ca_dir = silver_path("corporate_actions", settings)
    if not ca_dir.exists():
        warnings.append("corporate_actions directory not found")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    df = read_parquet(ca_dir).collect()
    stats["total_rows"] = len(df)

    splits = df.filter(pl.col("action_type") == "split")
    bad_splits = splits.filter(
        pl.col("split_coefficient").is_null() | (pl.col("split_coefficient") <= 0)
    )
    if len(bad_splits) > 0:
        errors.append(f"{len(bad_splits)} splits with non-positive factor")
    stats["bad_split_factors"] = len(bad_splits)

    dividends = df.filter(pl.col("action_type") == "dividend")
    bad_divs = dividends.filter(
        pl.col("cash_amount").is_not_null() & (pl.col("cash_amount") < 0)
    )
    if len(bad_divs) > 0:
        errors.append(f"{len(bad_divs)} dividends with negative cash_amount")
    stats["bad_dividend_amounts"] = len(bad_divs)

    dup_count = len(df) - len(df.unique(subset=CORPORATE_ACTIONS_PK))
    if dup_count > 0:
        errors.append(f"{dup_count} duplicate corporate actions")
    stats["pk_dupes"] = dup_count

    log.info(
        "qa_corporate_actions: %d errors, %d warnings", len(errors), len(warnings)
    )
    return {"errors": errors, "warnings": warnings, "stats": stats}
