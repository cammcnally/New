"""Gold mart: wide-format macro context table."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import gold_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("gold.macro_context")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)

    macro_dir = silver_path("macro_asof_daily", settings)
    if not macro_dir.exists():
        log.warning("silver macro_asof_daily not found: %s", macro_dir)
        return {"rows": 0}

    out_dir = gold_path("gold_macro_context", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    macro = (
        read_parquet(macro_dir)
        .filter((pl.col("asof_date") >= sd) & (pl.col("asof_date") <= ed))
        .select("asof_date", "series_id", "value")
        .collect()
    )
    if len(macro) == 0:
        log.warning("no macro data in date range")
        return {"rows": 0}

    wide = macro.pivot(
        on="series_id",
        index="asof_date",
        values="value",
    ).sort("asof_date")

    wide = wide.with_columns(pl.col("asof_date").dt.year().alias("year"))

    rows = write_parquet(wide, out_dir, partition_by=["year"])
    log.info(
        "gold_macro_context: %d rows, %d series -> %s",
        rows,
        len(wide.columns) - 2,
        out_dir,
    )
    return {"rows": rows}
