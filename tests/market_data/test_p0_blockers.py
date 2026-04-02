"""P0 tests: Stooq ticker normalization, angle-bracket headers, settings overrides."""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

pytestmark = pytest.mark.ingestion


def test_stooq_ticker_strips_us_suffix(tmp_path: Path) -> None:
    """aapl.us.txt must produce symbol='AAPL', not 'AAPL.US'."""
    csv_content = "Date,Open,High,Low,Close,Volume\n20240301,150.0,155.0,149.0,153.0,1000000\n"
    stooq_file = tmp_path / "aapl.us.txt"
    stooq_file.write_text(csv_content)

    from market_data.bronze.normalize_stooq_daily import _parse_stooq_csv
    df = _parse_stooq_csv(stooq_file)

    assert df is not None
    assert len(df) == 1
    assert df["symbol"][0] == "AAPL"


def test_stooq_ticker_no_suffix(tmp_path: Path) -> None:
    """Plain filename without country suffix still works."""
    csv_content = "Date,Open,High,Low,Close,Volume\n20240301,150.0,155.0,149.0,153.0,1000000\n"
    stooq_file = tmp_path / "MSFT.txt"
    stooq_file.write_text(csv_content)

    from market_data.bronze.normalize_stooq_daily import _parse_stooq_csv
    df = _parse_stooq_csv(stooq_file)

    assert df is not None
    assert df["symbol"][0] == "MSFT"


def test_stooq_angle_bracket_headers(tmp_path: Path) -> None:
    """Stooq files with <OPEN>,<CLOSE>,<DTYYYYMMDD> headers must parse correctly."""
    csv_content = "<TICKER>,<DTYYYYMMDD>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>\nAAPL,20240301,150.0,155.0,149.0,153.0,1000000\n"
    stooq_file = tmp_path / "aapl.us.txt"
    stooq_file.write_text(csv_content)

    from market_data.bronze.normalize_stooq_daily import _parse_stooq_csv
    df = _parse_stooq_csv(stooq_file)

    assert df is not None
    assert len(df) == 1
    assert df["symbol"][0] == "AAPL"
    assert df["trade_date"][0] == date(2024, 3, 1)
    assert df["close"][0] == 153.0
    assert df["volume"][0] == 1000000.0


def test_settings_populate_by_name() -> None:
    """CLI overrides by field name must actually populate settings."""
    from market_data.common.settings import IngestionSettings

    s = IngestionSettings(
        alpha_vantage_api_key="test",
        fred_api_key="test",
        sec_user_agent="Test test@test.com",
        log_level="DEBUG",
    )
    assert s.log_level == "DEBUG"

    s2 = IngestionSettings(
        ALPHA_VANTAGE_API_KEY="test",
        FRED_API_KEY="test",
        SEC_USER_AGENT="Test test@test.com",
        LOG_LEVEL="WARNING",
    )
    assert s2.log_level == "WARNING"


def test_stooq_av_join_produces_rows(tmp_path: Path) -> None:
    """Critical join: Stooq bronze (symbol='AAPL') must match AV listing (symbol='AAPL')."""
    from market_data.common.io_parquet import write_parquet, read_parquet

    bronze_prices = pl.DataFrame({
        "symbol": ["AAPL", "AAPL", "MSFT"],
        "trade_date": [date(2024, 3, 1), date(2024, 3, 4), date(2024, 3, 1)],
        "open": [150.0, 152.0, 400.0],
        "high": [155.0, 156.0, 405.0],
        "low": [149.0, 151.0, 399.0],
        "close": [153.0, 154.0, 402.0],
        "volume": [1e6, 1.1e6, 2e6],
        "source_vendor": ["stooq"] * 3,
        "loaded_at": [datetime(2024, 3, 5, tzinfo=timezone.utc)] * 3,
        "year": [2024, 2024, 2024],
    }).with_columns(
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )

    master = pl.DataFrame({
        "sid": ["1", "2"],
        "symbol_current": ["AAPL", "MSFT"],
    })

    px_dir = tmp_path / "bronze_prices"
    sm_path = tmp_path / "security_master" / "security_master.parquet"
    write_parquet(bronze_prices, px_dir, partition_by=["year"])
    write_parquet(master, sm_path)

    prices_lf = read_parquet(px_dir)
    sm_lf = read_parquet(sm_path).select("sid", "symbol_current")

    joined = prices_lf.join(sm_lf, left_on="symbol", right_on="symbol_current", how="inner").collect()

    assert len(joined) == 3, f"Expected 3 joined rows, got {len(joined)}"
    assert set(joined["sid"].to_list()) == {"1", "2"}
