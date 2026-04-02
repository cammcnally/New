"""Gold mart: daily panel built from adjusted prices plus canonical identity."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import gold_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("gold.daily_panel")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)

    prices_dir = silver_path("prices_1d_split_adjusted", settings)
    membership_dir = silver_path("universe_membership", settings)
    master_dir = silver_path("instrument_master", settings)

    for name, path in [
        ("prices_1d_split_adjusted", prices_dir),
        ("universe_membership", membership_dir),
        ("instrument_master", master_dir),
    ]:
        if not path.exists():
            log.warning("silver %s not found: %s", name, path)
            return {"rows": 0}

    out_dir = gold_path("gold_daily_panel", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    prices = (
        read_parquet(prices_dir)
        .filter((pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed))
        .collect()
    )
    if len(prices) == 0:
        log.warning("no adjusted prices in date range")
        return {"rows": 0}

    members = (
        read_parquet(membership_dir)
        .filter(
            (pl.col("is_member") == True)  # noqa: E712
            & (pl.col("universe_name") == "all_us_common_daily")
            & (pl.col("trade_date") >= sd)
            & (pl.col("trade_date") <= ed)
        )
        .select("sid", "trade_date")
        .collect()
    )
    if len(members) == 0:
        log.warning("no universe members found")
        return {"rows": 0}

    panel = prices.join(members, on=["sid", "trade_date"], how="inner")

    master = (
        read_parquet(master_dir)
        .select(
            pl.col("instrument_id").cast(pl.Utf8).alias("sid"),
            pl.col("canonical_symbol").alias("symbol"),
            "exchange",
            "asset_type",
            pl.col("is_active_current").alias("is_active"),
        )
        .collect()
    )
    panel = panel.join(master, on="sid", how="left")

    panel = (
        panel.select(
            [
                "sid",
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "cum_split_factor",
                "cum_total_return_factor",
                "exchange",
                "asset_type",
                "is_active",
            ]
        )
        .sort(["sid", "trade_date"])
        .with_columns(pl.col("trade_date").dt.year().alias("year"))
    )

    rows = write_parquet(panel, out_dir, partition_by=["year"])
    log.info("gold_daily_panel: %d rows -> %s", rows, out_dir)
    return {"rows": rows}
