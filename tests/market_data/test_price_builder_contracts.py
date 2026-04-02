from __future__ import annotations

import json
from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import write_parquet
from market_data.common.paths import bronze_path, qa_dir, silver_path
from market_data.common.io_parquet import read_parquet
from market_data.silver.build_prices_1d_unadjusted import build as build_prices_1d_unadjusted

pytestmark = pytest.mark.ingestion


def test_build_prices_1d_unadjusted_quarantines_invalid_ohlc_and_keeps_valid_rows(test_settings) -> None:
    bronze_dir = bronze_path("yfinance_prices_1d", test_settings)
    bronze_dir.mkdir(parents=True, exist_ok=True)
    bronze = pl.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "trade_date": [date(2024, 1, 2), date(2024, 1, 3)],
            "open": [10.0, 10.0],
            "high": [9.0, 11.0],
            "low": [8.0, 9.0],
            "close": [10.5, 10.5],
            "volume": [1000.0, 1200.0],
            "source_vendor": ["yfinance", "yfinance"],
            "loaded_at": [
                datetime(2024, 1, 3, tzinfo=timezone.utc),
                datetime(2024, 1, 4, tzinfo=timezone.utc),
            ],
            "year": [2024, 2024],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(bronze, bronze_dir, partition_by=["year"])

    symbol_history_path = (
        silver_path("instrument_symbol_history", test_settings)
        / "instrument_symbol_history.parquet"
    )
    symbol_history = pl.DataFrame(
        {
            "instrument_id": [1],
            "source": ["yfinance"],
            "raw_source_symbol": ["AAA"],
            "normalized_source_symbol": ["AAA"],
            "effective_from_date": [date(2020, 1, 1)],
            "effective_to_date": [None],
            "is_primary_for_source": [True],
            "ingested_at_utc": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
        }
    ).with_columns(
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(symbol_history, symbol_history_path)

    result = build_prices_1d_unadjusted(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("prices_1d_unadjusted", test_settings)).collect()
    report_path = qa_dir(test_settings) / "invalid_ohlc_prices_1d.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["rows"] == 1
    assert result["invalid_ohlc_rows"] == 1
    assert out["trade_date"].to_list() == [date(2024, 1, 3)]
    assert report["summary"]["invalid_ohlc_rows"] == 1
    assert report["sample_rows"][0]["trade_date"] == "2024-01-02"


def test_build_prices_1d_unadjusted_refuses_security_master_fallback_and_reports_unresolved_identity(
    test_settings,
) -> None:
    bronze_dir = bronze_path("yfinance_prices_1d", test_settings)
    bronze_dir.mkdir(parents=True, exist_ok=True)
    bronze = pl.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "loaded_at": [datetime(2024, 1, 3, tzinfo=timezone.utc)],
            "year": [2024],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(bronze, bronze_dir, partition_by=["year"])

    master_path = silver_path("security_master", test_settings) / "security_master.parquet"
    master = pl.DataFrame(
        {
            "sid": ["S1"],
            "symbol_current": ["AAA"],
            "symbol_vendor": ["AAA"],
            "exchange": ["NYSE"],
            "asset_type": ["stock"],
            "country": ["US"],
            "currency": ["USD"],
            "ipo_date": [date(2020, 1, 1)],
            "delist_date": [None],
            "is_active": [True],
            "cik": [None],
            "sector": [None],
            "industry": [None],
            "source_priority": [1],
            "first_seen_at": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "last_seen_at": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "valid_from": [date(2020, 1, 1)],
            "valid_to": [date(2099, 12, 31)],
        }
    ).with_columns(
        pl.col("delist_date").cast(pl.Date),
        pl.col("cik").cast(pl.Utf8),
        pl.col("sector").cast(pl.Utf8),
        pl.col("industry").cast(pl.Utf8),
        pl.col("source_priority").cast(pl.Int32),
        pl.col("first_seen_at").cast(pl.Datetime("us", "UTC")),
        pl.col("last_seen_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(master, master_path)

    result = build_prices_1d_unadjusted(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=True,
    )

    report_path = qa_dir(test_settings) / "unresolved_identity_prices_1d.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["rows"] == 0
    assert result["unresolved_rows"] == 1
    assert result["used_security_master_fallback"] is False
    assert report["summary"]["unresolved_rows"] == 1
    assert report["summary"]["canonical_symbol_history_present"] is False
    assert report["sample_rows"][0]["source_vendor"] == "yfinance"
