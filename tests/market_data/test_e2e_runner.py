from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from market_data.orchestration import e2e as e2e_module
from market_data.common.manifest import build_manifest, dataset_manifest_path, read_manifest, write_manifest

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
   PyPortfolioOpt: Provides advanced optimization tools to maximize returns for a specific target risk.
Riskfolio-Lib: A specialized library for portfolio optimization and quantitative risk management.     )

    state = json.loads(e2e_module._paths(test_settings)["state"].read_text(encoding="utf-8"))
    assert state["current_stage"] == "canonical_market_data"
    assert state["last_failed_stage"] == "canonical_market_data"


def test_capture_market_data_logs_writes_stage_log(test_settings) -> None:
    e2e_module._ensure_dirs(test_settings)
    logger = e2e_module.logging.getLogger("market_data.test")

    with e2e_module._capture_market_data_logs(stage="canonical_market_data", settings=test_settings) as log_path:
        logger.warning("canonical log line")

    log_text = Path(log_path).read_text(encoding="utf-8")
    assert "canonical log line" in log_text


def test_dependency_sync_retries_without_cache_after_windows_cache_lock(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    e2e_module._ensure_dirs(test_settings)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "\n".join(
                    [
                        "Failed to read from the distribution cache",
                        "failed to rename file",
                        "os error 32",
                    ]
                ),
            )
        return subprocess.CompletedProcess(command, 0, "sync ok", "")

    monkeypatch.setattr(e2e_module.subprocess, "run", fake_run)

    log_path, command = e2e_module._run_dependency_sync(test_settings)

    assert calls[0] == e2e_module._dependency_sync_command()
    assert calls[1] == e2e_module._dependency_sync_command(no_cache=True)
    assert command.endswith("--no-cache")
    assert "retry after uv cache lock" in Path(log_path).read_text(encoding="utf-8")


def test_dependency_sync_retries_after_repo_venv_helper_process_lock(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    e2e_module._ensure_dirs(test_settings)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                command,
                2,
                "",
                (
                    "error: failed to remove file "
                    "`E:\\stock_csvs_AI-Perspective\\NEW\\.venv\\Lib\\site-packages\\bottleneck/"
                    "move.cp311-win_amd64.pyd`: Access is denied. (os error 5)"
                ),
            )
        return subprocess.CompletedProcess(command, 0, "sync ok", "")

    monkeypatch.setattr(e2e_module.subprocess, "run", fake_run)
    monkeypatch.setattr(e2e_module, "_terminate_repo_venv_helper_processes", lambda: [17092])

    log_path, command = e2e_module._run_dependency_sync(test_settings)

    assert calls[0] == e2e_module._dependency_sync_command()
    assert calls[1] == e2e_module._dependency_sync_command()
    assert command == " ".join(e2e_module._dependency_sync_command())
    assert "retry after terminating repo venv helper processes: [17092]" in Path(log_path).read_text(encoding="utf-8")


def test_dependency_sync_cleans_orphaned_bottleneck_after_successful_sync(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    e2e_module._ensure_dirs(test_settings)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, "sync ok", "")
        if len(calls) == 2:
            return subprocess.CompletedProcess(command, 1, "", "ImportError: Can't determine version for bottleneck")
        return subprocess.CompletedProcess(command, 0, "runtime ok", "")

    monkeypatch.setattr(e2e_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        e2e_module,
        "_cleanup_orphaned_bottleneck",
        lambda: ["E:/stock_csvs_AI-Perspective/NEW/.venv/Lib/site-packages/bottleneck"],
    )

    log_path, command = e2e_module._run_dependency_sync(test_settings)

    assert calls[0] == e2e_module._dependency_sync_command()
    assert calls[1] == e2e_module._dependency_runtime_check_command()
    assert calls[2] == e2e_module._dependency_runtime_check_command()
    assert command == " ".join(e2e_module._dependency_sync_command())
    assert "retry after cleaning orphaned bottleneck" in Path(log_path).read_text(encoding="utf-8")


def test_run_e2e_clears_stale_blocker_fields_after_successful_stage(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    state_paths = e2e_module._paths(test_settings)
    state_paths["root"].mkdir(parents=True, exist_ok=True)
    state_paths["state"].write_text(
        json.dumps(
            {
                "last_failed_stage": "dependency_sync",
                "blocker_classification": "fixable_issue",
                "blocker_message": "old error",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        e2e_module,
        "_run_dependency_sync",
        lambda settings: ("E:/tmp/dependency_sync.log", "uv sync"),
    )

    e2e_module.run_e2e(
        settings=test_settings,
        bootstrap_start_date="2010-01-01",
        panel_path="panel_ohlcv_clean.csv",
        pipeline_output_dir="pipeline_outputs",
        from_stage="dependency_sync",
        stop_after="dependency_sync",
    )

    state = json.loads(state_paths["state"].read_text(encoding="utf-8"))
    assert state["last_failed_stage"] is None
    assert state["blocker_classification"] is None
    assert state["blocker_message"] is None


def test_write_dataset_manifest_preserves_canonical_manifest_fields(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    manifest_path = dataset_manifest_path(test_settings)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(
        build_manifest(
            datasets=[],
            run_id="canonical-run",
            dataset_build_id="dataset-build-existing",
            reports={
                "canonical_build_manifest": str(manifest_path),
                "final_pass_fail_summary": "E:/tmp/final_pass_fail_summary.json",
            },
            domain_statuses={"required_core": {"status": "ready"}},
            final_status="passed_with_warnings",
            canonical_export_ready=True,
            compatibility_fallback_used=False,
        ),
        manifest_path,
    )

    monkeypatch.setattr(
        e2e_module,
        "_collect_manifest_datasets",
        lambda settings: [
            {
                "name": "instrument_master",
                "layer": "silver",
                "source_inputs": ["bronze/av_listing_status"],
                "row_count": 123,
                "partitions": [],
                "content_hash": "abc123",
            }
        ],
    )
    monkeypatch.setattr(
        e2e_module,
        "_verification_artifacts",
        lambda settings: [{"name": "qa_audit_findings", "path": "E:/tmp/audit_findings.json"}],
    )

    manifest = e2e_module._write_dataset_manifest(test_settings)
    saved = read_manifest(manifest_path)

    assert manifest["run_id"] == "canonical-run"
    assert saved["canonical_export_ready"] is True
    assert saved["domain_statuses"]["required_core"]["status"] == "ready"
    assert saved["final_status"] == "passed_with_warnings"
    assert saved["reports"]["final_pass_fail_summary"] == "E:/tmp/final_pass_fail_summary.json"
    assert saved["verification_artifacts"] == [{"name": "qa_audit_findings", "path": "E:/tmp/audit_findings.json"}]
    assert saved["datasets"][0]["name"] == "instrument_master"
