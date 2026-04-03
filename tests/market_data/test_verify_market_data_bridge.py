from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from market_data.common.io_parquet import write_parquet
from market_data.common.manifest import build_manifest, write_manifest
from market_data.common.paths import manifest_dir, qa_dir, silver_path
from market_data.bridge.export_pipeline_panel import export_panel
from tools.verify_market_data_bridge import run_checks

pytestmark = pytest.mark.ingestion

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def _write_universe_membership(
    test_settings,
    *,
    sid: str,
    trade_date: date,
    universe: str = "all_us_common_daily",
) -> None:
    membership_dir = silver_path("universe_membership", test_settings)
    membership_dir.mkdir(parents=True, exist_ok=True)
    membership = pl.DataFrame(
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
    write_parquet(membership, membership_dir / "membership.parquet")


def _required_report_paths(test_settings) -> dict[str, str]:
    qa_root = qa_dir(test_settings)
    qa_root.mkdir(parents=True, exist_ok=True)
    manifest_root = manifest_dir(test_settings)
    manifest_root.mkdir(parents=True, exist_ok=True)
    report_map = {
        "source_coverage_report": qa_root / "source_coverage.json",
        "unresolved_identity_report": qa_root / "unresolved_identity_prices_1d.json",
        "quarantine_report": qa_root / "quarantine_summary.json",
        "final_pass_fail_summary": manifest_root / "final_pass_fail_summary.json",
    }
    for path in report_map.values():
        path.write_text("{}", encoding="utf-8")
    return {name: str(path) for name, path in report_map.items()}


def _write_minimal_benchmark_support(test_settings) -> None:
    benchmark_prices = pl.DataFrame(
        {
            "sid": ["S1", "S1"],
            "trade_date": [date(2024, 1, 8), date(2024, 1, 9)],
            "open": [10.0, 10.1],
            "high": [11.0, 11.1],
            "low": [9.0, 9.1],
            "close": [10.5, 10.7],
            "volume": [1000.0, 1000.0],
            "source_vendor": ["test", "test"],
            "loaded_at": [
                datetime(2024, 1, 8, tzinfo=timezone.utc),
                datetime(2024, 1, 9, tzinfo=timezone.utc),
            ],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(
        benchmark_prices,
        silver_path("benchmark_prices_daily", test_settings) / "benchmark_prices.parquet",
    )
    security_master = pl.DataFrame(
        {
            "sid": ["S1"],
            "symbol_current": ["SPY"],
            "symbol_vendor": ["SPY"],
            "exchange": ["NYSE"],
            "asset_type": ["fund"],
            "country": ["US"],
            "currency": ["USD"],
            "ipo_date": [date(2020, 1, 1)],
            "delist_date": [None],
            "is_active": [True],
            "cik": [None],
            "sector": [None],
            "industry": [None],
            "source_priority": [1],
            "first_seen_at": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "last_seen_at": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "valid_from": [date(2020, 1, 1)],
            "valid_to": [date(9999, 12, 31)],
        }
    ).with_columns(
        pl.col("delist_date").cast(pl.Date),
        pl.col("cik").cast(pl.Utf8),
        pl.col("sector").cast(pl.Utf8),
        pl.col("industry").cast(pl.Utf8),
        pl.col("source_priority").cast(pl.Int32),
        pl.col("first_seen_at").cast(pl.Datetime("us", "UTC")),
        pl.col("last_seen_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        security_master,
        silver_path("security_master", test_settings) / "security_master.parquet",
    )


def test_bridge_verifier_fails_when_required_panel_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="missing export panel"):
        run_checks(
            panel_path=str(tmp_path / "missing-panel.csv"),
            require_manifest=True,
            data_lake=str(tmp_path),
            config_dir=str(_CONFIG_DIR),
        )


def test_bridge_verifier_rejects_git_lfs_pointer(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.csv"
    panel_path.write_text(
        "\n".join(
            [
                "version https://git-lfs.github.com/spec/v1",
                "oid sha256:deadbeef",
                "size 123",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="Git LFS pointer"):
        run_checks(
            panel_path=str(panel_path),
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
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            reports=_required_report_paths(test_settings),
            domain_statuses={
                "required_core": {"status": "ready", "blocking_failures": [], "warnings": []},
                "optional_enrichment": {"status": "deferred_or_partial", "warnings": []},
            },
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


def test_bridge_verifier_can_require_benchmark_side_artifact(
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
    _write_minimal_benchmark_support(test_settings)

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-bench",
            canonical_export_ready=True,
            reports=_required_report_paths(test_settings),
            domain_statuses={
                "required_core": {"status": "ready", "blocking_failures": [], "warnings": []},
                "optional_enrichment": {"status": "deferred_or_partial", "warnings": []},
            },
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

    assert (
        run_checks(
            panel_path=str(panel_path),
            require_manifest=True,
            require_benchmark_artifacts=True,
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )
        == 0
    )


def test_bridge_warns_when_dataset_manifest_lacks_domain_gate(
    test_settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
            run_id="dataset-build-legacy",
            canonical_export_ready=True,
            reports=_required_report_paths(test_settings),
            domain_statuses={
                "required_core": {"status": "ready", "blocking_failures": [], "warnings": []},
                "optional_enrichment": {"status": "deferred_or_partial", "warnings": []},
            },
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

    legacy_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    legacy_manifest.pop("domain_statuses", None)
    dataset_manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")

    assert (
        run_checks(
            panel_path=str(panel_path),
            require_manifest=True,
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )
        == 0
    )
    assert "skipping domain/report linkage checks" in capsys.readouterr().out


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
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            reports=_required_report_paths(test_settings),
            domain_statuses={
                "required_core": {"status": "ready", "blocking_failures": [], "warnings": []},
                "optional_enrichment": {"status": "deferred_or_partial", "warnings": []},
            },
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
    _write_universe_membership(test_settings, sid="S1", trade_date=date(2024, 1, 8))

    dataset_manifest_path = manifest_dir(test_settings) / "dataset_manifest.json"
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="dataset-build-1",
            canonical_export_ready=True,
            reports=_required_report_paths(test_settings),
            domain_statuses={
                "required_core": {"status": "ready", "blocking_failures": [], "warnings": []},
                "optional_enrichment": {"status": "deferred_or_partial", "warnings": []},
            },
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
