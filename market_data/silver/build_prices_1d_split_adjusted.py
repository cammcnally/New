"""Silver: split-adjusted daily OHLCV from unadjusted prices and adjustment factors.

Price series contract:
  - prices_1d_unadjusted: raw tradeable prices, no adjustments
  - prices_1d_split_adjusted: backward split-adjusted for chart continuity
  - prices_1d_total_return: split + dividend reinvestment (deferred)
"""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.schema_registry import PRICES_1D_SPLIT_ADJUSTED
from market_data.common.settings import IngestionSettings

log = get_logger("silver.prices_1d_split_adjusted")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    px_dir = silver_path("prices_1d_unadjusted", settings)
    adj_dir = silver_path("adjustment_factors", settings)
    out_dir = silver_path("prices_1d_split_adjusted", settings)

    if not px_dir.exists():
        log.warning("silver prices_1d_unadjusted not found: %s", px_dir)
        return {"rows": 0}

    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    prices = (
        read_parquet(px_dir)
        .filter((pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed))
        .collect()
        .sort(["sid", "trade_date"])
    )

    if len(prices) == 0:
        log.warning("no prices in date range")
        return {"rows": 0}

    loaded = utc_now()

    if not adj_dir.exists():
        adj = pl.DataFrame(
            schema={
                "sid": pl.Utf8,
                "effective_date": pl.Date,
                "cum_split_factor": pl.Float64,
                "cum_total_return_factor": pl.Float64,
            }
        )
    else:
        adj = (
            read_parquet(adj_dir)
            .select("sid", "effective_date", "cum_split_factor", "cum_total_return_factor")
            .collect()
            .sort(["sid", "effective_date"])
        )

    if len(adj) == 0:
        out = prices.with_columns(
            [
                pl.lit(1.0).alias("cum_split_factor"),
                pl.lit(1.0).alias("cum_total_return_factor"),
                pl.lit(loaded).alias("loaded_at"),
            ]
        )
    else:
        out = prices.join_asof(
            adj,
            left_on="trade_date",
            right_on="effective_date",
            by="sid",
            strategy="backward",
        ).with_columns(
            [
                pl.col("cum_split_factor").fill_null(1.0),
                pl.col("cum_total_return_factor").fill_null(1.0),
                pl.lit(loaded).alias("loaded_at"),
            ]
        )

        f = pl.col("cum_split_factor")
        out = out.with_columns(
            [
                (pl.col("open") * f).alias("open"),
                (pl.col("high") * f).alias("high"),
                (pl.col("low") * f).alias("low"),
                (pl.col("close") * f).alias("close"),
                (pl.col("volume") / f).alias("volume"),
            ]
        )

    keep = list(PRICES_1D_SPLIT_ADJUSTED.keys())
    out = out.select([c for c in keep if c in out.columns])

    for col, dtype in PRICES_1D_SPLIT_ADJUSTED.items():
        if col in out.columns and out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(dtype))

    out = out.with_columns(pl.col("trade_date").dt.year().alias("year"))

    rows = write_parquet(out, out_dir, partition_by=["year"])
    log.info("silver prices_1d_split_adjusted: %d rows", rows)
    return {"rows": rows}
