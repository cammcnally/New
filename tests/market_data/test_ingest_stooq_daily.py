from __future__ import annotations

import pytest

from market_data.common.source_catalog import SourceDefinition
from market_data.raw import ingest_stooq_daily as stooq_daily

pytestmark = pytest.mark.ingestion


def test_ingest_skips_unbounded_per_ticker_fallback_for_supplemental_source(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    monkeypatch.setattr(stooq_daily, "_try_bulk_download", lambda dest: None)
    monkeypatch.setattr(
        stooq_daily,
        "load_source_catalog",
        lambda settings: {
            "stooq": SourceDefinition(
                name="stooq",
                enabled=True,
                source_class="supplemental_support",
                roles=("ohlcv_daily_secondary",),
                raw_datasets=("daily",),
                bronze_datasets=("stooq_daily",),
                notes="",
            )
        },
    )

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("per-ticker fallback should be skipped")

    monkeypatch.setattr(stooq_daily, "_per_ticker_download", _boom)

    result = stooq_daily.ingest(
        settings=test_settings,
        start_date="2026-04-02",
        end_date="2026-04-02",
        full_refresh=False,
    )

    assert result["method"] == "skipped_bulk_unavailable"
    assert result["warning"] == "bulk_zip_unavailable"
