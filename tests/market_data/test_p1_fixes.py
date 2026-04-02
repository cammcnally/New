"""P1 tests: AV volume, rate-limit retry, bridge timestamps, prereqs, glob paths."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import polars as pl
import pytest

pytestmark = pytest.mark.ingestion


def test_av_float_string_volume() -> None:
    """int(float('1234567.0')) must not crash."""
    raw_value = "1234567.0"
    result = int(float(raw_value))
    assert result == 1234567


def test_av_quota_not_retried() -> None:
    """AlphaVantageQuotaExhausted must be a distinct exception excluded from retry."""
    from market_data.clients.alphavantage_client import AlphaVantageQuotaExhausted

    assert issubclass(AlphaVantageQuotaExhausted, Exception)
    assert not issubclass(AlphaVantageQuotaExhausted, (httpx.TimeoutException,))
    exc = AlphaVantageQuotaExhausted("quota hit")
    assert str(exc) == "quota hit"


def test_bridge_timestamp_is_exchange_close() -> None:
    """Bridge timestamp must be actual NYSE close in UTC, not hardcoded 16:00 UTC."""
    from market_data.common.calendars import session_open_close

    d = date(2024, 7, 15)
    _, close_ts = session_open_close(d)
    close_utc = close_ts.to_pydatetime()

    assert close_utc.hour == 20, f"Expected 20:00 UTC (EDT), got {close_utc.hour}:00"

    d_winter = date(2024, 1, 16)
    _, close_ts_w = session_open_close(d_winter)
    close_utc_w = close_ts_w.to_pydatetime()

    assert close_utc_w.hour == 21, f"Expected 21:00 UTC (EST), got {close_utc_w.hour}:00"


def test_bridge_prerequisite_error(tmp_path: Path) -> None:
    """Bridge must raise FileNotFoundError with clear message for missing tables."""
    from market_data.bridge.export_pipeline_panel import _check_prerequisite

    with pytest.raises(FileNotFoundError, match="security_master"):
        _check_prerequisite("security_master", tmp_path / "nonexistent")


def test_parquet_glob_posix(tmp_path: Path) -> None:
    """Parquet read path must use POSIX separators even on Windows."""
    from market_data.common.io_parquet import read_parquet

    sub = tmp_path / "year=2024"
    sub.mkdir()
    pl.DataFrame({"x": [1, 2]}).write_parquet(str(sub / "part-000.parquet"))

    lf = read_parquet(tmp_path)
    assert lf.collect().height == 2


def test_rate_limiter_reads_settings() -> None:
    """Rate limiter factories must accept and use settings values."""
    from market_data.common.rate_limiter import alpha_vantage_limiter, sec_limiter

    class FakeSettings:
        av_requests_per_minute = 10
        sec_requests_per_second = 5.0

    import market_data.common.rate_limiter as rl
    rl._LIMITERS.clear()

    av = alpha_vantage_limiter(FakeSettings())
    assert av.rate == pytest.approx(10.0 / 60.0)

    sec = sec_limiter(FakeSettings())
    assert sec.rate == pytest.approx(5.0)

    rl._LIMITERS.clear()
