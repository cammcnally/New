from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Prefer repo root so `import market_data` resolves to the ingestion package.
# Do not add `tests/market_data/__init__.py`: with pytest, `tests/` is on
# sys.path and a package named `market_data` under `tests/` shadows the real
# `market_data` package (`ModuleNotFoundError: market_data.common`).
sys.path.insert(0, str(_REPO_ROOT))

from market_data.common.schema_registry import PRICES_1D_UNADJUSTED
from market_data.common.settings import IngestionSettings


@pytest.fixture
def tmp_lake(tmp_path: Path) -> Path:
    root = tmp_path / "data_lake"
    for sub in ("raw", "bronze", "silver", "gold", "qa", "manifests"):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def test_settings(tmp_lake: Path) -> IngestionSettings:
    return IngestionSettings(
        data_lake_root=tmp_lake,
        configs_dir=_REPO_ROOT / "configs",
        alpha_vantage_api_key="test_key",
        fred_api_key="test_key",
        sec_user_agent="Test Agent test@test.com",
    )


@pytest.fixture
def sample_listing_df() -> pl.DataFrame:
    """Bronze av_listing_status–style frame (see normalize_alphavantage_listing_status)."""
    return pl.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD", "EEE"],
            "name": ["A Inc", "B Co", "C Ltd", "D Corp", "E LLC"],
            "exchange": ["NYSE"] * 5,
            "asset_type": ["Stock"] * 5,
            "ipo_date": [None, None, None, None, None],
            "delist_date": [None, None, None, None, None],
            "status": ["Active"] * 5,
            "source_vendor": ["alphavantage"] * 5,
            "loaded_at": [datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)] * 5,
        }
    ).with_columns(
        [
            pl.col("ipo_date").cast(pl.Date),
            pl.col("delist_date").cast(pl.Date),
            pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
        ]
    )


@pytest.fixture
def sample_prices_df() -> pl.DataFrame:
    """Daily OHLCV for two symbols over 10 session days."""
    rows: list[dict] = []
    sids = ("S1", "S2")
    start = date(2024, 1, 2)
    loaded = datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    for sid in sids:
        for i in range(10):
            td = date.fromordinal(start.toordinal() + i)
            o, h, l, c = 10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i
            rows.append(
                {
                    "sid": sid,
                    "trade_date": td,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": 1_000_000.0 + i,
                    "source_vendor": "test",
                    "source_symbol": sid,
                    "loaded_at": loaded,
                }
            )
    df = pl.DataFrame(rows)
    for col, dtype in PRICES_1D_UNADJUSTED.items():
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(dtype))
    return df
