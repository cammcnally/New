from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_data.orchestration import e2e as e2e_module

pytestmark = pytest.mark.ingestion


def test_run_e2e_resume_requires_identical_fingerprint(test_settings) -> None:
    state_paths = e2e_module._paths(test_settings)
    state_paths["root"].mkdir(parents=True, exist_ok=True)
    fingerprint = e2e_module._fingerprint(
        settings=test_settings,
        bootstrap_start_date="2010-01-01",
        panel_path=(e2e_module._REPO_ROOT / "panel_ohlcv_clean.csv").resolve(),
        pipeline_output_dir=(e2e_module._REPO_ROOT / "pipeline_outputs").resolve(),
    )
    fingerprint["panel_path"] = str((e2e_module._REPO_ROOT / "different-panel.csv").resolve())
    state_paths["state"].write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "status": "partial_progress",
                "last_successful_stage": "export_panel",
                "stage_records": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="configuration or output paths changed"):
        e2e_module.run_e2e(
            settings=test_settings,
            bootstrap_start_date="2010-01-01",
            panel_path="panel_ohlcv_clean.csv",
            pipeline_output_dir="pipeline_outputs",
            resume=True,
        )


def test_run_e2e_resume_returns_existing_completed_status(test_settings) -> None:
    state_paths = e2e_module._paths(test_settings)
    state_paths["root"].mkdir(parents=True, exist_ok=True)
    fingerprint = e2e_module._fingerprint(
        settings=test_settings,
        bootstrap_start_date="2010-01-01",
        panel_path=(e2e_module._REPO_ROOT / "panel_ohlcv_clean.csv").resolve(),
        pipeline_output_dir=(e2e_module._REPO_ROOT / "pipeline_outputs").resolve(),
    )
    status_payload = {
        "status": "completed",
        "authoritative_command": "uv run python tools/run_repo_e2e.py",
        "resume_command": "uv run python tools/run_repo_e2e.py --resume",
    }
    state_paths["state"].write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "status": "completed",
                "last_successful_stage": "finalize_status",
                "stage_records": [],
            }
        ),
        encoding="utf-8",
    )
    state_paths["status_json"].write_text(json.dumps(status_payload), encoding="utf-8")

    result = e2e_module.run_e2e(
        settings=test_settings,
        bootstrap_start_date="2010-01-01",
        panel_path="panel_ohlcv_clean.csv",
        pipeline_output_dir="pipeline_outputs",
        resume=True,
    )

    assert result == status_payload


def test_build_status_payload_uses_effective_runner_arguments(test_settings) -> None:
    fingerprint = {
        "data_lake_root": "E:/custom-lake",
        "configs_dir": "E:/custom-configs",
        "bootstrap_start_date": "2011-01-01",
        "panel_path": "E:/custom-run/custom_panel.csv",
        "pipeline_output_dir": "E:/custom-run/custom_outputs",
    }

    payload = e2e_module._build_status_payload(
        settings=test_settings,
        stage_records=[],
        guard_results=e2e_module._empty_guard_results(),
        status="partial_progress",
        panel_path=(e2e_module._REPO_ROOT / "panel_ohlcv_clean.csv").resolve(),
        pipeline_output_dir=(e2e_module._REPO_ROOT / "pipeline_outputs").resolve(),
        fingerprint=fingerprint,
        run_started_at="2026-04-02T00:00:00Z",
        run_finished_at="2026-04-02T00:01:00Z",
    )

    assert "--data-lake E:/custom-lake" in payload["authoritative_command"]
    assert "--config-dir E:/custom-configs" in payload["authoritative_command"]
    assert "--bootstrap-start-date 2011-01-01" in payload["authoritative_command"]
    assert "--panel-path E:/custom-run/custom_panel.csv" in payload["authoritative_command"]
    assert "--pipeline-output-dir E:/custom-run/custom_outputs" in payload["authoritative_command"]
    assert payload["resume_command"].endswith("--resume")


def test_finalize_status_reuses_complete_pre_export_guard_evidence() -> None:
    guard_results = e2e_module._empty_guard_results()
    for guard in ("schema_guard", "docs_sync_guard", "pit_guard", "compat_guard", "bridge_guard"):
        guard_results[guard]["result"] = "passed"

    assert e2e_module._has_complete_pre_export_guard_evidence(guard_results) is True


def test_finalize_status_detects_missing_pre_export_guard_evidence() -> None:
    guard_results = e2e_module._empty_guard_results()
    guard_results["schema_guard"]["result"] = "passed"

    assert e2e_module._has_complete_pre_export_guard_evidence(guard_results) is False


def test_run_e2e_persists_current_stage_before_inprocess_failure(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    def _boom(**kwargs):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(e2e_module, "run_bootstrap", _boom)

    with pytest.raises(KeyboardInterrupt, match="stop"):
        e2e_module.run_e2e(
            settings=test_settings,
            bootstrap_start_date="2010-01-01",
            panel_path="panel_ohlcv_clean.csv",
            pipeline_output_dir="pipeline_outputs",
            from_stage="canonical_market_data",
            stop_after="canonical_market_data",
        )

    state = json.loads(e2e_module._paths(test_settings)["state"].read_text(encoding="utf-8"))
    assert state["current_stage"] == "canonical_market_data"
    assert state["last_failed_stage"] == "canonical_market_data"
