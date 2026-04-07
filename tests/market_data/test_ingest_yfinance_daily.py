from __future__ import annotations

import json

import pytest

from market_data.common.paths import raw_path
from market_data.raw import ingest_yfinance_daily as yfinance_daily

pytestmark = pytest.mark.ingestion


def _write_listing_status(test_settings, rows: list[dict[str, str]]) -> None:
    listing_dir = raw_path("alphavantage", "listing_status", test_settings)
    listing_dir.mkdir(parents=True, exist_ok=True)
    (listing_dir / "listing_status_test.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )


def test_load_symbols_excludes_delisted_before_requested_window(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    monkeypatch.setattr(yfinance_daily, "benchmark_symbols", lambda settings: [])
    _write_listing_status(
        test_settings,
        [
            {
                "symbol": "AAA",
                "name": "Active Company",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Active",
                "_av_state": "active",
            },
            {
                "symbol": "BBB",
                "name": "Old Delisted Company",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Delisted",
                "_av_state": "delisted",
                "delistingDate": "2024-10-03",
            },
            {
                "symbol": "CCC",
                "name": "Recently Delisted Company",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Delisted",
                "_av_state": "delisted",
                "delistingDate": "2026-04-03",
            },
        ],
    )

    symbols, exclusions = yfinance_daily._load_symbols(test_settings, start_date="2026-04-03")

    assert symbols == ["AAA", "CCC"]
    assert {"symbol": "BBB", "reason": "delisted_before_window"} in exclusions


def test_load_symbols_keeps_delisted_symbols_for_overlapping_historical_window(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    monkeypatch.setattr(yfinance_daily, "benchmark_symbols", lambda settings: [])
    _write_listing_status(
        test_settings,
        [
            {
                "symbol": "BBB",
                "name": "Old Delisted Company",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Delisted",
                "_av_state": "delisted",
                "delistingDate": "2024-10-03",
            }
        ],
    )

    symbols, exclusions = yfinance_daily._load_symbols(test_settings, start_date="2024-01-01")

    assert symbols == ["BBB"]
    assert exclusions == []


def test_load_symbols_excludes_active_non_core_symbol_variants(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    monkeypatch.setattr(yfinance_daily, "benchmark_symbols", lambda settings: [])
    _write_listing_status(
        test_settings,
        [
            {
                "symbol": "ABR-P-D",
                "name": "Arbor Realty Trust Inc",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Active",
                "_av_state": "active",
            },
            {
                "symbol": "ACHR-WS",
                "name": "Archer Aviation Inc Wt",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Active",
                "_av_state": "active",
            },
            {
                "symbol": "BIZD:BAT",
                "name": "VanEck BDC Income ETF",
                "exchange": "NYSE ARCA",
                "assetType": "ETF",
                "status": "Active",
                "_av_state": "active",
            },
            {
                "symbol": "BRK-B",
                "name": "Berkshire Hathaway Inc Class B",
                "exchange": "NYSE",
                "assetType": "Stock",
                "status": "Active",
                "_av_state": "active",
            },
        ],
    )

    symbols, exclusions = yfinance_daily._load_symbols(test_settings, start_date="2026-04-03")

    assert symbols == ["BRK-B"]
    assert {"symbol": "ABR-P-D", "reason": "preferred_share"} in exclusions
    assert {"symbol": "ACHR-WS", "reason": "symbol_scope_exclusion"} in exclusions
    assert {"symbol": "BIZD:BAT", "reason": "vendor_special_symbol"} in exclusions
