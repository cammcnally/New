"""Gold mart: basic feature engineering on daily panel (placeholder)."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import gold_path
from market_data.common.settings import IngestionSettings

log = get_logger("gold.feature_base")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)

    panel_dir = gold_path("gold_daily_panel", settings)
    if not panel_dir.exists():
        log.warning("gold_daily_panel not found: %s", panel_dir)
        return {"rows": 0}

    out_dir = gold_path("gold_feature_base", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    panel = (
        read_parquet(panel_dir)
        .filter((pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed))
        .sort(["sid", "trade_date"])
        .collect()
    )
    if len(panel) == 0:
        log.warning("no daily panel data in date range")
        return {"rows": 0}

    features = (
        panel.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("sid") - 1).alias(
                "returns_1d"
            ),
            (pl.col("volume") + 1).log().alias("log_volume"),
            (pl.col("close") / pl.col("close").shift(20).over("sid") - 1).alias(
                "momentum_20d"
            ),
        )
        .with_columns(
            pl.col("returns_1d")
            .rolling_std(window_size=20, min_periods=20)
            .over("sid")
            .alias("volatility_20d"),
        )
        .with_columns(pl.col("trade_date").dt.year().alias("year"))
    )

    rows = write_parquet(features, out_dir, partition_by=["year"])
    log.info("gold_feature_base: %d rows -> %s", rows, out_dir)
    return {"rows": rows}
