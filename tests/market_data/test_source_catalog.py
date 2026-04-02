from __future__ import annotations

import pytest

from market_data.orchestration import run_bronze, run_raw

pytestmark = pytest.mark.ingestion


def test_source_catalog_normalizes_repo_wide_source_policy(test_settings) -> None:
    from market_data.common.source_catalog import load_source_catalog

    catalog = load_source_catalog(test_settings)

    assert catalog["yfinance"].source_class == "required_core"
    assert catalog["alphavantage"].source_class == "required_core"
    assert catalog["stooq"].source_class == "supplemental_support"
    assert catalog["sec"].source_class == "optional_enrichment"
    assert catalog["fred"].source_class == "optional_enrichment"

    assert "ohlcv_daily_primary" in catalog["yfinance"].roles
    assert "listing_metadata_primary" in catalog["alphavantage"].roles
    assert "company_fundamentals_authoritative_when_available" in catalog["sec"].roles
    assert catalog["yfinance"].raw_datasets == ("daily",)
    assert catalog["yfinance"].bronze_datasets == ("yfinance_daily",)


def test_raw_and_bronze_orchestration_follow_source_catalog(test_settings) -> None:
    from market_data.common.source_catalog import enabled_bronze_datasets, enabled_raw_sources

    assert run_raw.available_sources(test_settings) == enabled_raw_sources(test_settings)
    assert run_bronze.available_datasets(test_settings) == enabled_bronze_datasets(test_settings)
    assert "yfinance" in run_raw.available_sources(test_settings)
    assert "yfinance_daily" in run_bronze.available_datasets(test_settings)
