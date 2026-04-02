from __future__ import annotations

import importlib
from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.paths import silver_path
from market_data.silver.build_benchmark_prices_daily import build as build_benchmark_prices_daily

pytestmark = pytest.mark.ingestion


def test_build_benchmark_definitions_emits_canonical_catalog(test_settings) -> None:
    module = importlib.import_module("market_data.silver.build_benchmark_definitions")
    build_benchmark_definitions = module.build

    result = build_benchmark_definitions(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("benchmark_definitions", test_settings)).collect()

    assert result["rows"] >= 3
    assert "benchmark_id" in out.columns
    assert out["benchmark_id"].n_unique() == out.height
    assert "^VIX" in out["symbol"].to_list()
    assert "VIXY" in out["symbol"].to_list()
    assert "SPY" in out["symbol"].to_list()
    assert (out.filter(pl.col("symbol") == "SPY")["benchmark_id"].item()) == "bm_SPY"


def test_build_benchmark_prices_daily_uses_canonical_instrument_master(
    test_settings,
) -> None:
    instrument_master = pl.DataFrame(
        {
            "instrument_id": [9001],
            "asset_type": ["fund"],
            "security_type": ["etf"],
            "canonical_symbol": ["SPY"],
            "legal_name": ["SPDR S&P 500 ETF Trust"],
            "exchange": ["NYSE ARCA"],
            "primary_country": ["US"],
            "currency": ["USD"],
            "is_active_current": [True],
            "first_seen_date": [date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 10)],
            "source_priority": [1],
            "created_at_utc": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "updated_at_utc": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
        }
    ).with_columns(
        pl.col("source_priority").cast(pl.Int32),
        pl.col("created_at_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("updated_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        instrument_master,
        silver_path("instrument_master", test_settings) / "instrument_master.parquet",
    )

    prices = pl.DataFrame(
        {
            "sid": ["9001"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "source_symbol": ["SPY"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, silver_path("prices_1d_unadjusted", test_settings) / "prices.parquet")

    result = build_benchmark_prices_daily(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("benchmark_prices_daily", test_settings)).collect()

    assert result["rows"] == 1
    assert out["sid"].to_list() == ["9001"]
