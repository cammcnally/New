from __future__ import annotations

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet
from market_data.common.paths import silver_path
from market_data.silver.build_trading_calendar import build as build_trading_calendar

pytestmark = pytest.mark.ingestion


def test_build_trading_calendar_emits_contract_valid_schedule(test_settings) -> None:
    result = build_trading_calendar(
        settings=test_settings,
        start_date="2024-01-05",
        end_date="2024-01-07",
        full_refresh=True,
    )

    out = read_parquet(silver_path("trading_calendar", test_settings)).collect()

    assert result["rows"] == 3
    assert {
        "trade_date",
        "exchange",
        "is_trading_day",
        "market_open_utc",
        "market_close_utc",
        "is_early_close",
        "loaded_at",
    }.issubset(set(out.columns))
    assert out.filter(pl.col("is_trading_day")).height >= 1
    assert out.filter(~pl.col("is_trading_day")).height >= 1
