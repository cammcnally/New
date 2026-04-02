"""Test persistent monotonic SID registry."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

pytestmark = pytest.mark.ingestion


def test_sid_assignment_deterministic(tmp_path: Path) -> None:
    """SIDs must be assigned in sorted order and be stable across calls."""
    from market_data.common.settings import IngestionSettings

    settings = IngestionSettings(
        alpha_vantage_api_key="test",
        fred_api_key="test",
        sec_user_agent="Test test@test.com",
        data_lake_root=tmp_path / "lake",
    )

    listings = pl.DataFrame({
        "exchange": ["NASDAQ", "NYSE", "NASDAQ"],
        "symbol": ["AAPL", "IBM", "GOOG"],
        "status": ["active", "active", "active"],
        "name": ["Apple", "IBM Corp", "Alphabet"],
    })

    from market_data.silver.sid_registry import assign_sids, load_registry

    result = assign_sids(listings, settings)
    assert "sid" in result.columns
    assert result["sid"].null_count() == 0
    sids = result.sort("sid")["sid"].to_list()
    assert sids == [1, 2, 3]

    result2 = assign_sids(listings, settings)
    sids2 = result2.sort("sid")["sid"].to_list()
    assert sids == sids2, "SIDs must be stable across calls"


def test_sid_new_symbols_appended(tmp_path: Path) -> None:
    """New symbols must get appended IDs, not reassigned."""
    from market_data.common.settings import IngestionSettings

    settings = IngestionSettings(
        alpha_vantage_api_key="test",
        fred_api_key="test",
        sec_user_agent="Test test@test.com",
        data_lake_root=tmp_path / "lake",
    )

    batch1 = pl.DataFrame({
        "exchange": ["NYSE", "NASDAQ"],
        "symbol": ["IBM", "AAPL"],
        "status": ["active", "active"],
        "name": ["IBM", "Apple"],
    })

    from market_data.silver.sid_registry import assign_sids

    r1 = assign_sids(batch1, settings)
    ibm_sid = r1.filter(pl.col("symbol") == "IBM")["sid"][0]

    batch2 = pl.DataFrame({
        "exchange": ["NYSE", "NASDAQ", "NASDAQ"],
        "symbol": ["IBM", "AAPL", "TSLA"],
        "status": ["active", "active", "active"],
        "name": ["IBM", "Apple", "Tesla"],
    })

    r2 = assign_sids(batch2, settings)
    assert r2.filter(pl.col("symbol") == "IBM")["sid"][0] == ibm_sid
    assert r2.filter(pl.col("symbol") == "TSLA")["sid"][0] == 3
