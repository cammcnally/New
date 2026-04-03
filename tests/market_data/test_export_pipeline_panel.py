from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import json

import polars as pl
import pytest

from market_data.bridge.export_pipeline_panel import export_panel
from market_data.common.io_parquet import write_parquet
from market_data.common.manifest import build_manifest, stable_content_id, write_manifest
from market_data.common.pandera_contracts import ContractValidationError
from market_data.common.paths import manifest_dir, silver_path

pytestmark = pytest.mark.ingestion


def _write_universe_membership(
    test_settings,
    *,
    sid: str,
    trade_date: date,
    universe: str = "all_us_common_daily",
) -> None:
    mdir = silver_path("universe_membership", test_settings)
    mdir.mkdir(parents=True, exist_ok=True)
    m = pl.DataFrame(
        {
            "trade_date": [trade_date],
            "sid": [sid],
            "universe_name": [universe],
            "is_member": [True],
            "is_primary_listing": [True],
            "is_common_stock": [True],
            "price_ok": [True],
            "liquidity_ok": [True],
            "age_ok": [True],
            "status_ok": [True],
            "eligibility_reason": [""],
        }
    )
    write_parquet(m, mdir / "membership.parquet")


def test_export_panel_rejects_rows_without_market_close_timestamp(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 6)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 7, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")

    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 6))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            final_status="passed",
        ),
        dataset_manifest_path,
    )

    with pytest.raises(ContractValidationError, match="pandera validation failed"):
        export_panel(
            settings=test_settings,
            output_path=str(tmp_path / "panel.csv"),
            start_date="2024-01-01",
            end_date="2024-01-10",
        )


def test_export_panel_writes_sidecar_manifest_with_dataset_build_id(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")

    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            final_status="passed",
        ),
        dataset_manifest_path,
    )

    output_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(output_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    export_manifest_path = Path(str(output_path) + ".manifest.json")
    assert export_manifest_path.exists()

    export_manifest = json.loads(export_manifest_path.read_text())
    assert export_manifest["dataset_build_id"] == "dataset-build-1"
    assert export_manifest["contract_name"] == "export_panel"
    assert export_manifest["row_count"] == 1
    assert export_manifest["ticker_count"] == 1
    assert export_manifest["start_date"] == "2024-01-01"
    assert export_manifest["end_date"] == "2024-01-10"
    assert export_manifest["content_hash"]
    assert export_manifest["export_panel_version_id"] == stable_content_id(
        "export-panel",
        export_manifest["content_hash"],
    )
    assert export_manifest["verification_artifacts"] == []
    assert export_manifest["deferred_components"] == []
    assert export_manifest.get("universe_filter_applied") is True


def test_export_panel_registers_export_manifest_in_dataset_manifest(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")

    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            final_status="passed",
        ),
        dataset_manifest_path,
    )

    output_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(output_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    assert dataset_manifest["reports"]["export_panel_manifest"] == str(
        Path(str(output_path) + ".manifest.json")
    )


def test_export_panel_writes_csv_without_pandas_conversion(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")

    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            final_status="passed",
        ),
        dataset_manifest_path,
    )

    monkeypatch.setattr(
        pl.DataFrame,
        "to_pandas",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(AssertionError("to_pandas should not be used")),
    )

    output_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(output_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    exported = pl.read_csv(output_path, try_parse_dates=True)
    assert exported["ticker"].to_list() == ["AAA"]


def test_export_panel_requires_canonical_ready_dataset_manifest(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")

    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=False,
            final_status="failed",
        ),
        dataset_manifest_path,
    )

    with pytest.raises(RuntimeError, match="canonical_export_ready"):
        export_panel(
            settings=test_settings,
            output_path=str(tmp_path / "panel.csv"),
            start_date="2024-01-01",
            end_date="2024-01-10",
        )
    assert not (tmp_path / "panel.csv").exists()


def test_export_panel_rejects_compatibility_fallback_manifest_without_writing_csv(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")

    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            compatibility_fallback_used=True,
            final_status="completed_with_warnings",
        ),
        dataset_manifest_path,
    )

    with pytest.raises(RuntimeError, match="compatibility_fallback_used"):
        export_panel(
            settings=test_settings,
            output_path=str(tmp_path / "panel.csv"),
            start_date="2024-01-01",
            end_date="2024-01-10",
        )
    assert not (tmp_path / "panel.csv").exists()


def test_export_panel_uses_date_effective_source_symbol_as_ticker(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["OLDAAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")
    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            final_status="passed",
        ),
        dataset_manifest_path,
    )

    output_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(output_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    exported = pl.read_csv(output_path, try_parse_dates=True)
    assert exported["ticker"].to_list() == ["OLDAAA"]


def test_export_panel_skip_universe_filter_omits_membership_and_marks_manifest(
    test_settings,
    tmp_path: Path,
) -> None:
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 8)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["test"],
            "source_symbol": ["AAA"],
            "loaded_at": [datetime(2024, 1, 8, tzinfo=timezone.utc)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(prices, prices_dir / "prices.parquet")
    silver_path("trading_calendar", test_settings).mkdir(parents=True, exist_ok=True)

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            final_status="passed",
        ),
        dataset_manifest_path,
    )

    output_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(output_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
        skip_universe_filter=True,
    )
    manifest = json.loads(Path(str(output_path) + ".manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("universe_filter_applied") is False
