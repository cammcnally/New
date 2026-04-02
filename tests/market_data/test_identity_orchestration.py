from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import pytest

from market_data.orchestration import run_silver, sync

pytestmark = pytest.mark.ingestion


def test_run_silver_build_order_starts_with_canonical_identity() -> None:
    assert run_silver.SILVER_BUILD_ORDER[:4] == [
        "instrument_master",
        "instrument_symbol_history",
        "benchmark_definitions",
        "security_master",
    ]
    assert run_silver._BUILDERS["security_master"] == "market_data.silver.compat_security_master"


def test_sync_critical_path_delegates_to_shared_canonical_runner() -> None:
    source = inspect.getsource(sync._run_critical_path)

    assert "run_all" in source
    assert "ingest_yf" not in source
    assert "build_instrument_master" not in source


def test_run_bootstrap_uses_shared_canonical_runner(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    calls: dict[str, object] = {}

    def _fake_run_all(**kwargs):  # type: ignore[no-untyped-def]
        calls.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(sync, "run_all", _fake_run_all)
    monkeypatch.setattr(sync, "today_utc", lambda: date(2024, 1, 31))
    monkeypatch.setattr(sync, "write_watermark", lambda *args, **kwargs: Path("watermark.json"))

    result = sync.run_bootstrap(
        settings=test_settings,
        start_date="2024-01-01",
    )

    assert result["status"] == "ok"
    assert calls["settings"] == test_settings
    assert calls["start_date"] == "2024-01-01"
    assert calls["end_date"] == "2024-01-31"
    assert calls["full_refresh"] is True
    assert calls["fail_fast"] is False


def test_run_sync_uses_shared_canonical_runner(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    calls: dict[str, object] = {}

    def _fake_run_all(**kwargs):  # type: ignore[no-untyped-def]
        calls.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(sync, "run_all", _fake_run_all)
    monkeypatch.setattr(sync, "today_utc", lambda: date(2024, 2, 5))
    monkeypatch.setattr(
        sync,
        "read_watermark",
        lambda settings: {"start_date": "2024-01-01", "end_date": "2024-02-01"},
    )
    monkeypatch.setattr(sync, "write_watermark", lambda *args, **kwargs: Path("watermark.json"))

    result = sync.run_sync(settings=test_settings)

    assert result["status"] == "ok"
    assert calls["settings"] == test_settings
    assert calls["start_date"] == "2024-02-01"
    assert calls["end_date"] == "2024-02-05"
    assert calls["full_refresh"] is False
    assert calls["fail_fast"] is False


def test_run_status_reports_canonical_identity_counts(test_settings) -> None:
    silver_root = Path(test_settings.data_lake_root) / "silver"
    (silver_root / "instrument_master").mkdir(parents=True, exist_ok=True)
    (silver_root / "instrument_symbol_history").mkdir(parents=True, exist_ok=True)
    (silver_root / "security_master").mkdir(parents=True, exist_ok=True)
    (silver_root / "prices_1d_unadjusted").mkdir(parents=True, exist_ok=True)
    (silver_root / "trading_calendar").mkdir(parents=True, exist_ok=True)

    status = sync.run_status(settings=test_settings)
    counts = status["silver_row_counts"]

    assert isinstance(counts, dict)
    assert "instrument_master" in counts
    assert "instrument_symbol_history" in counts
