"""Silver: corporate actions from Alpha Vantage daily adjusted bronze."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import bronze_path, silver_path
from market_data.common.schema_registry import CORPORATE_ACTIONS
from market_data.common.settings import IngestionSettings

log = get_logger("silver.corporate_actions")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    bronze_dir = bronze_path("av_daily_adjusted", settings)
    sm_path = silver_path("security_master", settings)
    ca_dir = silver_path("corporate_actions", settings)
    out_path = ca_dir / "corporate_actions.parquet"

    if not bronze_dir.exists():
        log.warning("bronze av_daily_adjusted not found: %s", bronze_dir)
        return {"rows": 0}
    if not sm_path.exists():
        log.warning("silver security_master not found: %s", sm_path)
        return {"rows": 0}

    if full_refresh and ca_dir.exists():
        shutil.rmtree(ca_dir)

    sm = read_parquet(sm_path).select("sid", "symbol_current")

    base = (
        read_parquet(bronze_dir)
        .filter((pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed))
        .join(sm, left_on="symbol", right_on="symbol_current", how="inner")
    )

    loaded = utc_now()
    split_rows = base.filter(pl.col("split_coefficient") != 1.0).with_columns(
        [
            pl.lit("split").alias("action_type"),
            pl.col("trade_date").alias("ex_date"),
            pl.col("dividend_amount").cast(pl.Float64).alias("cash_amount"),
            pl.col("split_coefficient").cast(pl.Float64),
            pl.lit(None).cast(pl.Date).alias("record_date"),
            pl.lit(None).cast(pl.Date).alias("payment_date"),
            pl.lit(None).cast(pl.Date).alias("declared_date"),
            pl.lit("alphavantage").alias("source_vendor"),
            pl.lit(loaded).alias("loaded_at"),
        ]
    )

    div_rows = base.filter(pl.col("dividend_amount") > 0.0).with_columns(
        [
            pl.lit("dividend").alias("action_type"),
            pl.col("trade_date").alias("ex_date"),
            pl.col("dividend_amount").cast(pl.Float64).alias("cash_amount"),
            pl.lit(1.0).alias("split_coefficient"),
            pl.lit(None).cast(pl.Date).alias("record_date"),
            pl.lit(None).cast(pl.Date).alias("payment_date"),
            pl.lit(None).cast(pl.Date).alias("declared_date"),
            pl.lit("alphavantage").alias("source_vendor"),
            pl.lit(loaded).alias("loaded_at"),
        ]
    )

    cols = [
        "sid",
        "action_type",
        "ex_date",
        "cash_amount",
        "split_coefficient",
        "record_date",
        "payment_date",
        "declared_date",
        "source_vendor",
        "loaded_at",
    ]

    split_df = split_rows.select(cols).collect()
    div_df = div_rows.select(cols).collect()

    if len(split_df) == 0 and len(div_df) == 0:
        log.warning("no corporate actions in date range")
        return {"rows": 0}

    out = pl.concat([split_df, div_df], how="vertical")

    for col, dtype in CORPORATE_ACTIONS.items():
        if col in out.columns and out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(dtype))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = write_parquet(out, out_path)
    log.info("silver corporate_actions: %d rows", rows)
    return {"rows": rows}

