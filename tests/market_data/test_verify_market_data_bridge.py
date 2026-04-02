from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from market_data.common.io_parquet import write_parquet
from market_data.common.manifest import build_manifest, write_manifest
from market_data.common.paths import manifest_dir, silver_path
from market_data.bridge.export_pipeline_panel import export_panel
from tools.verify_market_data_bridge import run_checks

pytestmark = pytest.mark.ingestion

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def test_bridge_verifier_fails_when_required_panel_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="missing export panel"):
        run_checks(
            panel_path=str(tmp_path / "missing-panel.csv"),
            require_manifest=True,
            data_lake=str(tmp_path),
            config_dir=str(_CONFIG_DIR),
        )


def test_bridge_verifier_requires_dataset_manifest_to_register_export_manifest(
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

    panel_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(panel_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    dataset_manifest["reports"]["export_panel_manifest"] = None
    dataset_manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    with pytest.raises(SystemExit, match="dataset manifest export_panel_manifest mismatch"):
        run_checks(
            panel_path=str(panel_path),
            require_manifest=True,
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )


def test_bridge_verifier_fails_when_dataset_manifest_is_not_canonical_ready(
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

    panel_path = tmp_path / "panel.csv"
    export_panel(
        settings=test_settings,
        output_path=str(panel_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    dataset_manifest["canonical_export_ready"] = False
    dataset_manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    with pytest.raises(SystemExit, match="dataset manifest canonical_export_ready=false"):
        run_checks(
            panel_path=str(panel_path),
            require_manifest=True,
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )


def test_bridge_verifier_normalizes_relative_export_manifest_path(
    test_settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    monkeypatch.chdir(tmp_path)
    panel_path = Path("panel.csv")
    export_panel(
        settings=test_settings,
        output_path=str(panel_path),
        start_date="2024-01-01",
        end_date="2024-01-10",
    )

    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    dataset_manifest["reports"]["export_panel_manifest"] = "panel.csv.manifest.json"
    dataset_manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    assert (
        run_checks(
            panel_path=str((tmp_path / "panel.csv").resolve()),
            require_manifest=True,
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )
        == 0
    )
