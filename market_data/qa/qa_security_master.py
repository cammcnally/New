"""QA checks for generated compatibility `security_master`."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("qa.security_master")


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    master_dir = silver_path("security_master", settings)
    if not master_dir.exists():
        errors.append("generated compatibility security_master directory not found")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    df = read_parquet(master_dir).collect()
    stats["total_rows"] = len(df)
    stats["unique_sids"] = df["sid"].n_unique()

    active = df.filter(pl.col("is_active"))
    dup_active = active.group_by("symbol_current").agg(pl.len().alias("n")).filter(
        pl.col("n") > 1
    )
    if len(dup_active) > 0:
        dupes = dup_active["symbol_current"].to_list()[:10]
        errors.append(f"duplicate active tickers: {dupes}")
    stats["duplicate_active_tickers"] = len(dup_active)

    sorted_df = df.sort(["sid", "valid_from"])
    overlaps = sorted_df.with_columns(
        pl.col("valid_to").shift(1).over("sid").alias("prev_valid_to"),
    ).filter(pl.col("valid_from") < pl.col("prev_valid_to"))
    if len(overlaps) > 0:
        errors.append(f"overlapping validity windows: {len(overlaps)} rows")
    stats["overlapping_windows"] = len(overlaps)

    bad_status = df.filter(pl.col("is_active") & pl.col("delist_date").is_not_null())
    if len(bad_status) > 0:
        warnings.append(f"active with delist_date set: {len(bad_status)} rows")
    stats["active_with_delist"] = len(bad_status)

    cik_filled = df.filter(pl.col("cik").is_not_null()).height
    cik_pct = cik_filled / len(df) * 100 if len(df) > 0 else 0.0
    stats["cik_coverage_pct"] = round(cik_pct, 2)
    if cik_pct < 50:
        warnings.append(f"CIK coverage is low: {cik_pct:.1f}%")

    log.info("qa_security_master: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
