from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.paths import bronze_path, silver_path
from market_data.common.settings import IngestionSettings
from market_data.orchestration.run_silver import SILVER_BUILD_ORDER
from market_data.silver.build_instrument_symbol_history import build as build_instrument_symbol_history
from market_data.silver.build_prices_1d_unadjusted import build as build_prices
from market_data.silver.build_security_master import build as build_security_master
from market_data.silver.build_symbol_map_history import build as build_symbol_map_history

pytestmark = pytest.mark.ingestion


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _write_instrument_master(settings: IngestionSettings) -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [101],
            "asset_type": ["equity"],
            "security_type": ["common_stock"],
            "canonical_symbol": ["AAA"],
            "legal_name": ["A Inc"],
            "exchange": ["NYSE"],
            "primary_country": ["US"],
            "currency": ["USD"],
            "is_active_current": [True],
            "first_seen_date": [date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 2)],
            "source_priority": [1],
            "created_at_utc": [_utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 2)],
        }
    ).with_columns(
        pl.col("source_priority").cast(pl.Int32),
        pl.col("created_at_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("updated_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        df,
        silver_path("instrument_master", settings) / "instrument_master.parquet",
    )


def _write_instrument_symbol_history(settings: IngestionSettings) -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [101],
            "source": ["yfinance"],
            "raw_source_symbol": ["AAA"],
            "normalized_source_symbol": ["AAA"],
            "effective_from_date": [date(2020, 1, 1)],
            "effective_to_date": [None],
            "is_primary_for_source": [True],
            "ingested_at_utc": [_utc(2024, 1, 2)],
        }
    ).with_columns(
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        df,
        silver_path("instrument_symbol_history", settings) / "instrument_symbol_history.parquet",
    )


def _write_bronze_prices(settings: IngestionSettings) -> None:
    df = pl.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(df, bronze_path("yfinance_prices_1d", settings) / "part-000.parquet")


def test_silver_build_order_starts_with_canonical_identity() -> None:
    assert SILVER_BUILD_ORDER[:4] == [
        "instrument_master",
        "instrument_symbol_history",
        "benchmark_definitions",
        "security_master",
    ]


def test_security_master_is_generated_from_instrument_master(test_settings) -> None:
    _write_instrument_master(test_settings)

    result = build_security_master(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=False,
    )

    out = read_parquet(silver_path("security_master", test_settings)).collect()

    assert result["rows"] == 1
    assert out["sid"].to_list() == ["101"]
    assert out["symbol_current"].to_list() == ["AAA"]


def test_symbol_map_history_is_generated_from_canonical_symbol_history(test_settings) -> None:
    _write_instrument_symbol_history(test_settings)

    result = build_symbol_map_history(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=False,
    )

    out = read_parquet(silver_path("symbol_map_history", test_settings)).collect()

    assert result["rows"] == 1
    assert out["sid"].to_list() == ["101"]
    assert out["symbol"].to_list() == ["AAA"]


def test_symbol_map_history_refuses_security_master_fallback_without_canonical_history(
    test_settings,
) -> None:
    security_master = pl.DataFrame(
        {
            "sid": ["101"],
            "symbol_current": ["AAA"],
            "ipo_date": [date(2020, 1, 1)],
            "valid_to": [None],
        }
    ).with_columns(pl.col("valid_to").cast(pl.Date))
    write_parquet(
        security_master,
        silver_path("security_master", test_settings) / "security_master.parquet",
    )

    result = build_symbol_map_history(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=False,
    )

    out_path = silver_path("symbol_map_history", test_settings) / "symbol_map_history.parquet"
    assert result["rows"] == 0
    assert result["canonical_symbol_history_present"] is False
    assert not out_path.exists()


def test_instrument_symbol_history_builder_matches_listing_status_to_active_state(test_settings) -> None:
    instrument_master = pl.DataFrame(
        {
            "instrument_id": [1728, 1729],
            "asset_type": ["equity", "equity"],
            "security_type": ["common_stock", "common_stock"],
            "canonical_symbol": ["ADSE", "ADSE"],
            "legal_name": ["Ads-Tec Energy Plc", "Ads-Tec Energy Plc"],
            "exchange": ["NASDAQ", "NASDAQ"],
            "primary_country": ["US", "US"],
            "currency": ["USD", "USD"],
            "is_active_current": [False, True],
            "first_seen_date": [date(2021, 3, 10), date(2021, 12, 23)],
            "last_seen_date": [date(2021, 12, 23), date(2024, 1, 2)],
            "source_priority": [1, 1],
            "created_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 2), _utc(2024, 1, 2)],
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

    listing_status = pl.DataFrame(
        {
            "symbol": ["ADSE", "ADSE"],
            "name": ["Ads-Tec Energy Plc", "Ads-Tec Energy Plc"],
            "exchange": ["NASDAQ", "NASDAQ"],
            "status": ["Delisted", "Active"],
            "ipo_date": [date(2021, 3, 10), date(2021, 12, 23)],
            "delist_date": [date(2021, 12, 23), None],
            "asset_type": ["Stock", "Stock"],
        }
    ).with_columns(pl.col("delist_date").cast(pl.Date))
    write_parquet(
        listing_status,
        bronze_path("av_listing_status", test_settings) / "listing_status.parquet",
    )

    result = build_instrument_symbol_history(
        settings=test_settings,
        start_date="2021-03-10",
        end_date="2024-01-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("instrument_symbol_history", test_settings)).collect().sort(
        ["source", "instrument_id"]
    )

    assert result["rows"] == 4
    assert out["source"].to_list() == ["alphavantage", "alphavantage", "yfinance", "yfinance"]
    assert out["instrument_id"].to_list() == [1728, 1729, 1728, 1729]
    assert out["effective_from_date"].to_list() == [
        date(2021, 3, 10),
        date(2021, 12, 23),
        date(2021, 3, 10),
        date(2021, 12, 23),
    ]


def test_prices_builder_uses_canonical_symbol_history_without_security_master(test_settings) -> None:
    _write_instrument_master(test_settings)
    _write_instrument_symbol_history(test_settings)
    _write_bronze_prices(test_settings)

    result = build_prices(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=False,
    )

    out = read_parquet(silver_path("prices_1d_unadjusted", test_settings)).collect()

    assert result["rows"] == 1
    assert out["sid"].to_list() == ["101"]
    assert out["source_symbol"].to_list() == ["AAA"]
