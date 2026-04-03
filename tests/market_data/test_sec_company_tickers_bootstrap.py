from __future__ import annotations

import json
from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.paths import bronze_path, raw_path, silver_path
from market_data.raw import ingest_sec_company_tickers as ingest_tickers
from market_data.raw import ingest_sec_companyfacts as ingest_facts
from market_data.raw import ingest_sec_submissions as ingest_submissions
from market_data.bronze.normalize_sec_company_tickers import normalize as normalize_tickers
from market_data.silver.compat_security_master import build as build_security_master

pytestmark = pytest.mark.ingestion


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_sec_company_tickers_ingest_writes_raw_bootstrap_json(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    payload = {
        "0": {"ticker": "AAA", "cik_str": 1, "title": "AAA Corp"},
        "1": {"ticker": "BBB", "cik_str": 2, "title": "BBB Corp"},
    }

    monkeypatch.setattr(
        "market_data.clients.sec_client.SecClient.fetch_company_tickers",
        lambda self: payload,
    )

    result = ingest_tickers.ingest(settings=test_settings)
    out_path = raw_path("sec", "company_tickers", test_settings) / "company_tickers.json"
    assert result["rows"] == 2
    assert out_path.exists()
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["0"]["ticker"] == "AAA"


def test_sec_company_tickers_normalize_and_security_master_cik_fill(test_settings) -> None:
    raw_dir = raw_path("sec", "company_tickers", test_settings)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "company_tickers.json").write_text(
        json.dumps(
            {
                "0": {"ticker": "AAA", "cik_str": 1, "title": "AAA Corp"},
                "1": {"ticker": "BBB", "cik_str": 2, "title": "BBB Corp"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    norm = normalize_tickers(settings=test_settings, full_refresh=True)
    assert norm["rows"] == 2
    bronze_df = read_parquet(
        bronze_path("sec_company_tickers", test_settings) / "company_tickers.parquet"
    ).collect()
    assert bronze_df["cik"].to_list() == ["0000000001", "0000000002"]

    instrument_master = pl.DataFrame(
        {
            "instrument_id": [1, 2],
            "asset_type": ["equity", "equity"],
            "security_type": ["common_stock", "common_stock"],
            "canonical_symbol": ["AAA", "BBB"],
            "legal_name": ["AAA Corp", "BBB Corp"],
            "exchange": ["NYSE", "NYSE"],
            "primary_country": ["US", "US"],
            "currency": ["USD", "USD"],
            "is_active_current": [True, True],
            "first_seen_date": [date(2020, 1, 1), date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 10), date(2024, 1, 10)],
            "source_priority": [1, 1],
            "created_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
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

    sec_master = build_security_master(settings=test_settings)
    out = read_parquet(
        silver_path("security_master", test_settings) / "security_master.parquet"
    ).collect()
    assert sec_master["rows"] == 2
    assert out.sort("symbol_current")["cik"].to_list() == ["0000000001", "0000000002"]


def test_sec_raw_cik_loaders_prefer_bronze_company_tickers(test_settings) -> None:
    instrument_master = pl.DataFrame(
        {
            "instrument_id": [1, 2],
            "asset_type": ["equity", "equity"],
            "security_type": ["common_stock", "common_stock"],
            "canonical_symbol": ["AAA", "BBB"],
            "legal_name": ["AAA Corp", "BBB Corp"],
            "exchange": ["NYSE", "NYSE"],
            "primary_country": ["US", "US"],
            "currency": ["USD", "USD"],
            "is_active_current": [True, True],
            "first_seen_date": [date(2020, 1, 1), date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 10), date(2024, 1, 10)],
            "source_priority": [1, 1],
            "created_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
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
    bronze_dir = bronze_path("sec_company_tickers", test_settings)
    bronze_dir.mkdir(parents=True, exist_ok=True)
    write_parquet(
        pl.DataFrame(
            {
                "ticker": ["AAA", "BBB", "ZZZ"],
                "cik": ["0000000001", "0000000002", "0000000999"],
                "company_name": ["AAA Corp", "BBB Corp", "ZZZ Corp"],
                "source_vendor": ["sec", "sec", "sec"],
                "loaded_at": [_utc(2024, 1, 1), _utc(2024, 1, 1), _utc(2024, 1, 1)],
            }
        ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC"))),
        bronze_dir / "company_tickers.parquet",
    )

    assert ingest_submissions._load_ciks(test_settings) == ["0000000001", "0000000002"]
    assert ingest_facts._load_ciks(test_settings) == ["0000000001", "0000000002"]


def test_sec_raw_cik_loaders_fallback_to_raw_company_tickers_when_bronze_missing(test_settings) -> None:
    instrument_master = pl.DataFrame(
        {
            "instrument_id": [1, 2],
            "asset_type": ["equity", "equity"],
            "security_type": ["common_stock", "common_stock"],
            "canonical_symbol": ["AAA", "BBB"],
            "legal_name": ["AAA Corp", "BBB Corp"],
            "exchange": ["NYSE", "NYSE"],
            "primary_country": ["US", "US"],
            "currency": ["USD", "USD"],
            "is_active_current": [True, True],
            "first_seen_date": [date(2020, 1, 1), date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 10), date(2024, 1, 10)],
            "source_priority": [1, 1],
            "created_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
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

    raw_dir = raw_path("sec", "company_tickers", test_settings)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "company_tickers.json").write_text(
        json.dumps(
            {
                "0": {"ticker": "AAA", "cik_str": 1, "title": "AAA Corp"},
                "1": {"ticker": "BBB", "cik_str": 2, "title": "BBB Corp"},
                "2": {"ticker": "ZZZ", "cik_str": 999, "title": "ZZZ Corp"},
            }
        ),
        encoding="utf-8",
    )

    assert ingest_submissions._load_ciks(test_settings) == ["0000000001", "0000000002"]
    assert ingest_facts._load_ciks(test_settings) == ["0000000001", "0000000002"]
