from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_data.bridge.export_pipeline_panel import export_panel
from market_data.common.dates import today_utc
from market_data.common.manifest import (
    build_dataset_build_id,
    build_manifest,
    dataset_manifest_path,
    read_manifest,
    read_watermark,
    write_manifest,
)
from market_data.common.paths import manifest_dir
from market_data.common.settings import IngestionSettings
from market_data.orchestration.run_all import (
    _DEFERRED_COMPONENTS,
    _collect_manifest_datasets,
    _verification_artifacts,
)
from market_data.orchestration.sync import run_bootstrap, run_sync
from tools.verify_market_data import run_checks as run_verification_bundle, run_compat_guard
from tools.verify_market_data_bridge import run_checks as run_bridge_checks
from tools.verify_market_data_contracts import run_checks as run_contract_checks
from tools.verify_market_data_docs_sync import run_checks as run_docs_sync_checks
from tools.verify_market_data_pit import run_checks as run_pit_checks

STAGES = [
    "dependency_sync",
    "canonical_market_data",
    "verify_market_data",
    "export_panel",
    "pipeline_run",
    "finalize_status",
]
GUARDS = [
    "schema_guard",
    "docs_sync_guard",
    "pit_guard",
    "compat_guard",
    "bridge_guard",
    "verification_guard",
]
_DOCS_SYNC_BASE_REF = "origin/main"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class StageRecord:
    stage: str
    status: str
    started_at: str
    finished_at: str
    command: str | None = None
    log_path: str | None = None
    primary_output: str | None = None
    outputs: dict[str, Any] | None = None
    notes: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(settings: IngestionSettings) -> dict[str, Path]:
    root = manifest_dir(settings)
    logs = root / "e2e_logs"
    return {
        "root": root,
        "logs": logs,
        "state": root / "repo_e2e_state.json",
        "status_json": root / "run_status.json",
        "status_md": root / "run_status.md",
        "verification_json": root / "verification_summary.json",
        "verification_md": root / "verification_summary.md",
    }


def _ensure_dirs(settings: IngestionSettings) -> None:
    p = _paths(settings)
    p["root"].mkdir(parents=True, exist_ok=True)
    p["logs"].mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _log_path(settings: IngestionSettings, stage: str) -> Path:
    return _paths(settings)["logs"] / f"{stage}.log"


def _run_subprocess(command: list[str], *, stage: str, settings: IngestionSettings) -> str:
    log_path = _log_path(settings, stage)
    result = subprocess.run(
        command,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    log_path.write_text(
        f"$ {' '.join(command)}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{stage} failed with exit code {result.returncode}. See {log_path}")
    return str(log_path)


def _dependency_sync_command(*, no_cache: bool = False) -> list[str]:
    command = [
        "uv",
        "sync",
        "--group",
        "dev",
        "--group",
        "control-plane",
        "--group",
        "ingestion",
        "--group",
        "ingestion-test",
        "--group",
        "data",
        "--group",
        "ml",
    ]
    if no_cache:
        command.append("--no-cache")
    return command


def _write_subprocess_log(
    path: Path,
    *,
    command: list[str],
    result: subprocess.CompletedProcess[str],
    note: str | None = None,
    append: bool = False,
) -> None:
    lines = []
    if note:
        lines.extend([f"[{note}]", ""])
    lines.extend(
        [
            f"$ {' '.join(command)}",
            "",
            "STDOUT:",
            result.stdout,
            "",
            "STDERR:",
            result.stderr,
        ]
    )
    payload = "\n".join(lines)
    if append and path.exists():
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n\n" + payload)
    else:
        path.write_text(payload, encoding="utf-8")


def _is_uv_cache_lock_failure(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return (
        "failed to read from the distribution cache" in text
        and "failed to rename file" in text
        and "os error 32" in text
    )


def _is_uv_venv_access_denied_failure(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return (
        "failed to remove file" in text
        and "access is denied" in text
        and "os error 5" in text
        and ".venv" in text
        and "site-packages" in text
    )


def _repo_venv_helper_pids() -> list[int]:
    if sys.platform != "win32":
        return []
    repo_python = (_REPO_ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    script = (
        "$repoPython = [System.IO.Path]::GetFullPath('"
        + str(repo_python).replace("'", "''")
        + "');"
        + f"$currentPid = {os.getpid()};"
        + "Get-CimInstance Win32_Process | Where-Object { "
        + "$_.ProcessId -ne $currentPid -and "
        + "$_.ExecutablePath -and "
        + "([System.IO.Path]::GetFullPath($_.ExecutablePath) -eq $repoPython) -and "
        + "$_.CommandLine"
        + " } | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    records = parsed if isinstance(parsed, list) else [parsed]
    markers = (
        "lsp_server.py",
        "mypy-type-checker",
        "pylance",
        "jedi",
        "ruff-lsp",
        "cursor\\extensions",
        "vscode",
    )
    pids: list[int] = []
    for record in records:
        command_line = str(record.get("CommandLine") or "").lower()
        if any(marker in command_line for marker in markers):
            pids.append(int(record["ProcessId"]))
    return pids


def _terminate_repo_venv_helper_processes() -> list[int]:
    pids = _repo_venv_helper_pids()
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    return pids


def _dependency_runtime_check_command() -> list[str]:
    return [sys.executable, "-c", "import pandas"]


def _is_broken_bottleneck_import(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "can't determine version for bottleneck" in text


def _cleanup_orphaned_bottleneck() -> list[str]:
    site_packages = _REPO_ROOT / ".venv" / "Lib" / "site-packages"
    targets = [site_packages / "bottleneck", *site_packages.glob("bottleneck-*.dist-info")]
    removed: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(str(target))
    return removed


def _validate_dependency_runtime(log_path: Path) -> None:
    command = _dependency_runtime_check_command()
    result = subprocess.run(
        command,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    _write_subprocess_log(log_path, command=command, result=result, note="post-sync runtime healthcheck", append=True)
    if result.returncode == 0:
        return
    if _is_broken_bottleneck_import(result):
        removed = _cleanup_orphaned_bottleneck()
        retry_result = subprocess.run(
            command,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        _write_subprocess_log(
            log_path,
            command=command,
            result=retry_result,
            note=f"retry after cleaning orphaned bottleneck: {removed}",
            append=True,
        )
        if retry_result.returncode == 0:
            return
        raise RuntimeError(
            f"dependency_sync runtime healthcheck failed with exit code {retry_result.returncode} after cleaning orphaned bottleneck. See {log_path}"
        )
    raise RuntimeError(f"dependency_sync runtime healthcheck failed with exit code {result.returncode}. See {log_path}")


def _run_dependency_sync(settings: IngestionSettings) -> tuple[str, str]:
    command = _dependency_sync_command()
    log_path = _log_path(settings, "dependency_sync")
    result = subprocess.run(
        command,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    _write_subprocess_log(log_path, command=command, result=result)
    if result.returncode == 0:
        _validate_dependency_runtime(log_path)
        return str(log_path), " ".join(command)
    if _is_uv_venv_access_denied_failure(result):
        terminated_pids = _terminate_repo_venv_helper_processes()
        if terminated_pids:
            retry_result = subprocess.run(
                command,
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            _write_subprocess_log(
                log_path,
                command=command,
                result=retry_result,
                note=f"retry after terminating repo venv helper processes: {terminated_pids}",
                append=True,
            )
            if retry_result.returncode == 0:
                _validate_dependency_runtime(log_path)
                return str(log_path), " ".join(command)
            if _is_uv_cache_lock_failure(retry_result):
                retry_command = _dependency_sync_command(no_cache=True)
                no_cache_retry = subprocess.run(
                    retry_command,
                    cwd=_REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                _write_subprocess_log(
                    log_path,
                    command=retry_command,
                    result=no_cache_retry,
                    note="retry after helper-process termination and uv cache lock",
                    append=True,
                )
                if no_cache_retry.returncode == 0:
                    _validate_dependency_runtime(log_path)
                    return str(log_path), " ".join(retry_command)
                raise RuntimeError(
                    f"dependency_sync failed with exit code {no_cache_retry.returncode} after terminating helper processes and cache-lock retry. See {log_path}"
                )
            raise RuntimeError(
                f"dependency_sync failed with exit code {retry_result.returncode} after terminating repo venv helper processes. See {log_path}"
            )
    if _is_uv_cache_lock_failure(result):
        retry_command = _dependency_sync_command(no_cache=True)
        retry_result = subprocess.run(
            retry_command,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        _write_subprocess_log(
            log_path,
            command=retry_command,
            result=retry_result,
            note="retry after uv cache lock",
            append=True,
        )
        if retry_result.returncode == 0:
            _validate_dependency_runtime(log_path)
            return str(log_path), " ".join(retry_command)
        raise RuntimeError(
            f"dependency_sync failed with exit code {retry_result.returncode} after cache-lock retry. See {log_path}"
        )
    raise RuntimeError(f"dependency_sync failed with exit code {result.returncode}. See {log_path}")


def _write_stage_marker(
    settings: IngestionSettings,
    *,
    stage: str,
    message: str,
) -> str:
    log_path = _log_path(settings, stage)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
    return str(log_path)


def _classify_blocker(exc: BaseException) -> str:
    text = str(exc).lower()
    hard_blocker_markers = (
        "api key",
        "credential",
        "permission denied",
        "quota",
        "auth",
        "source outage",
    )
    if any(marker in text for marker in hard_blocker_markers):
        return "hard_blocker"
    return "fixable_issue"


def _write_dataset_manifest(settings: IngestionSettings) -> dict[str, Any]:
    datasets = _collect_manifest_datasets(settings)
    manifest_path = dataset_manifest_path(settings)
    existing = read_manifest(manifest_path) if manifest_path.exists() else {}
    reports = existing.get("reports") if isinstance(existing, dict) and isinstance(existing.get("reports"), dict) else None
    domain_statuses = (
        existing.get("domain_statuses")
        if isinstance(existing, dict) and isinstance(existing.get("domain_statuses"), dict)
        else None
    )
    manifest = build_manifest(
        datasets=datasets,
        run_id=existing.get("run_id") if isinstance(existing, dict) else None,
        dataset_build_id=build_dataset_build_id(datasets) if datasets else existing.get("dataset_build_id"),
        verification_artifacts=_verification_artifacts(settings),
        deferred_components=existing.get("deferred_components", _DEFERRED_COMPONENTS)
        if isinstance(existing, dict)
        else _DEFERRED_COMPONENTS,
        reports=reports,
        domain_statuses=domain_statuses,
        final_status=str(existing.get("final_status", "unknown")) if isinstance(existing, dict) else "unknown",
        canonical_export_ready=bool(existing.get("canonical_export_ready")) if isinstance(existing, dict) else False,
        compatibility_fallback_used=bool(existing.get("compatibility_fallback_used"))
        if isinstance(existing, dict)
        else False,
    )
    write_manifest(manifest, manifest_path)
    return manifest


def _fingerprint(
    *,
    settings: IngestionSettings,
    bootstrap_start_date: str,
    panel_path: Path,
    pipeline_output_dir: Path,
) -> dict[str, str]:
    return {
        "data_lake_root": str(Path(settings.data_lake_root).resolve()),
        "configs_dir": str(Path(settings.configs_dir).resolve()),
        "bootstrap_start_date": bootstrap_start_date,
        "panel_path": str(panel_path.resolve()),
        "pipeline_output_dir": str(pipeline_output_dir.resolve()),
    }


def _build_runner_command(fingerprint: dict[str, str], *, resume: bool = False) -> str:
    parts = [
        "uv run python tools/run_repo_e2e.py",
        f"--data-lake {fingerprint['data_lake_root']}",
        f"--config-dir {fingerprint['configs_dir']}",
        f"--bootstrap-start-date {fingerprint['bootstrap_start_date']}",
        f"--panel-path {fingerprint['panel_path']}",
        f"--pipeline-output-dir {fingerprint['pipeline_output_dir']}",
    ]
    if resume:
        parts.append("--resume")
    return " ".join(parts)


def _empty_guard_results() -> dict[str, dict[str, str]]:
    return {guard: {"result": "", "evidence_path": "", "notes": ""} for guard in GUARDS}


def _has_complete_pre_export_guard_evidence(guard_results: dict[str, dict[str, str]]) -> bool:
    return all(
        guard_results.get(guard, {}).get("result") == "passed"
        for guard in ("schema_guard", "docs_sync_guard", "pit_guard", "compat_guard", "bridge_guard")
    )


def _load_stage_records(raw_records: list[dict[str, Any]] | None) -> list[StageRecord]:
    records: list[StageRecord] = []
    for item in raw_records or []:
        records.append(StageRecord(**item))
    return records


def _set_guard_result(
    guard_results: dict[str, dict[str, str]],
    *,
    guard: str,
    result: str,
    evidence_path: str | None = None,
    notes: str | None = None,
) -> None:
    guard_results.setdefault(guard, {"result": "", "evidence_path": "", "notes": ""})
    guard_results[guard]["result"] = result
    if evidence_path:
        guard_results[guard]["evidence_path"] = evidence_path
    if notes:
        guard_results[guard]["notes"] = notes


def _write_verification_summary(
    settings: IngestionSettings,
    guard_results: dict[str, dict[str, str]],
) -> tuple[str, str]:
    paths = _paths(settings)
    payload = {"generated_at_utc": _utc_now(), "guards": guard_results}
    _write_json(paths["verification_json"], payload)
    lines = [
        "# Verification Summary",
        "",
        "| Guard | Result | Evidence path | Notes |",
        "| ---- | ---- | ---- | ---- |",
    ]
    for guard in GUARDS:
        item = guard_results.get(guard, {})
        lines.append(
            f"| {guard} | {item.get('result', '')} | {item.get('evidence_path', '')} | {item.get('notes', '')} |"
        )
    paths["verification_md"].write_text("\n".join(lines), encoding="utf-8")
    return str(paths["verification_json"]), str(paths["verification_md"])


def _render_status_markdown(summary: dict[str, Any]) -> str:
    stage_lines = "\n".join(
        f"| {row['stage']} | {row['status']} | {row.get('command') or ''} | {row.get('primary_output') or ''} | {row.get('notes') or ''} |"
        for row in summary["stages"]
    )
    guard_lines = "\n".join(
        f"| {guard} | {summary['guards'][guard].get('result', '')} | {summary['guards'][guard].get('evidence_path', '')} | {summary['guards'][guard].get('notes', '')} |"
        for guard in GUARDS
    )
    return "\n".join(
        [
            "# Run Status",
            "",
            "## Summary",
            "",
            f"- status: `{summary['status']}`",
            f"- run_started_at: `{summary['run_started_at']}`",
            f"- run_finished_at: `{summary['run_finished_at']}`",
            f"- authoritative_command: `{summary['authoritative_command']}`",
            f"- resume_command: `{summary['resume_command']}`",
            f"- output_root: `{summary['output_root']}`",
            "",
            "## Build References",
            "",
            f"- dataset_build_id: `{summary.get('dataset_build_id')}`",
            f"- export_panel_version_id: `{summary.get('export_panel_version_id')}`",
            f"- dataset_manifest_path: `{summary.get('dataset_manifest_path')}`",
            f"- export_manifest_path: `{summary.get('export_manifest_path')}`",
            f"- verification_summary_path: `{summary.get('verification_json')}`",
            "",
            "## Stage Results",
            "",
            "| Stage | Result | Command | Primary output | Notes |",
            "| ---- | ---- | ---- | ---- | ---- |",
            stage_lines or "| | | | | |",
            "",
            "## Verification Guards",
            "",
            "| Guard | Result | Evidence path | Notes |",
            "| ---- | ---- | ---- | ---- |",
            guard_lines,
            "",
            "## Output Inventory",
            "",
            f"- canonical data updated: `{summary.get('canonical_data_updated')}`",
            f"- exported panel path: `{summary.get('exported_panel_path')}`",
            f"- pipeline output dir: `{summary.get('pipeline_output_dir')}`",
            f"- verification JSON: `{summary.get('verification_json')}`",
            f"- verification Markdown: `{summary.get('verification_markdown')}`",
            f"- final report path: `{summary.get('final_report_path')}`",
            f"- strategy report template path: `{summary.get('strategy_report_template_path')}`",
            f"- status summary path: `{summary.get('status_md_path')}`",
            "",
            "## Deferred Components",
            "",
            f"- deferred components observed: `{summary.get('deferred_components')}`",
            f"- deferred components reported in manifests: `{summary.get('deferred_components')}`",
            f"- impact on current run: `{summary.get('deferred_impact')}`",
            "",
            "## Blockers Or Warnings",
            "",
            f"- blocker summary: `{summary.get('blocker_message')}`",
            f"- warning summary: `{summary.get('warning_summary')}`",
            f"- next rerun command: `{summary.get('next_rerun_command')}`",
            "",
            "## Notes",
            "",
            f"- compatibility impact: `{summary.get('compatibility_impact')}`",
            f"- docs synchronized: `{summary.get('docs_synchronized')}`",
            f"- remaining follow-up: `{summary.get('remaining_follow_up')}`",
        ]
    )


def _build_status_payload(
    *,
    settings: IngestionSettings,
    stage_records: list[StageRecord],
    guard_results: dict[str, dict[str, str]],
    status: str,
    panel_path: Path,
    pipeline_output_dir: Path,
    fingerprint: dict[str, str],
    run_started_at: str,
    run_finished_at: str,
    blocker_classification: str | None = None,
    blocker_message: str | None = None,
) -> dict[str, Any]:
    state_paths = _paths(settings)
    dataset_manifest = _load_json(dataset_manifest_path(settings)) or {}
    export_manifest_path = Path(str(panel_path) + ".manifest.json")
    export_manifest = _load_json(export_manifest_path) or {}
    verification_json = str(state_paths["verification_json"])
    verification_md = str(state_paths["verification_md"])
    authoritative_command = _build_runner_command(fingerprint, resume=False)
    resume_command = _build_runner_command(fingerprint, resume=True)
    return {
        "status": status,
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "authoritative_command": authoritative_command,
        "resume_command": resume_command,
        "output_root": str(state_paths["root"]),
        "dataset_build_id": dataset_manifest.get("dataset_build_id") or export_manifest.get("dataset_build_id"),
        "export_panel_version_id": export_manifest.get("export_panel_version_id"),
        "dataset_manifest_path": str(dataset_manifest_path(settings)),
        "export_manifest_path": str(export_manifest_path),
        "verification_json": verification_json,
        "verification_markdown": verification_md,
        "exported_panel_path": str(panel_path),
        "pipeline_output_dir": str(pipeline_output_dir),
        "final_report_path": str(pipeline_output_dir / "05_reports" / "final_report.md"),
        "strategy_report_template_path": str((_REPO_ROOT / "strategy-report.qmd").resolve()),
        "status_md_path": str(state_paths["status_md"]),
        "state_path": str(state_paths["state"]),
        "canonical_data_updated": any(r.stage == "canonical_market_data" and r.status == "passed" for r in stage_records),
        "deferred_components": dataset_manifest.get("deferred_components", _DEFERRED_COMPONENTS),
        "deferred_impact": "sector-relative features remain disabled until deferred canonical classification work is implemented",
        "blocker_classification": blocker_classification,
        "blocker_message": blocker_message,
        "warning_summary": "",
        "next_rerun_command": resume_command if status != "completed" else "",
        "compatibility_impact": "Pipeline.py continues to consume the exported compatibility surface while market_data remains canonical.",
        "docs_synchronized": guard_results.get("docs_sync_guard", {}).get("result") == "passed",
        "remaining_follow_up": "Phase 7 lineage/DVC and final verification remain in progress." if status != "completed" else "",
        "guards": guard_results,
        "stages": [asdict(record) for record in stage_records],
    }


def _write_status_files(settings: IngestionSettings, payload: dict[str, Any]) -> None:
    state_paths = _paths(settings)
    _write_json(state_paths["status_json"], payload)
    state_paths["status_md"].write_text(_render_status_markdown(payload), encoding="utf-8")


def run_e2e(
    *,
    settings: IngestionSettings,
    bootstrap_start_date: str,
    panel_path: str,
    pipeline_output_dir: str,
    resume: bool = False,
    from_stage: str | None = None,
    stop_after: str | None = None,
) -> dict[str, Any]:
    _ensure_dirs(settings)
    state_paths = _paths(settings)
    state = _load_json(state_paths["state"]) or {}
    panel_path_obj = (_REPO_ROOT / panel_path).resolve()
    pipeline_output_path = (_REPO_ROOT / pipeline_output_dir).resolve()
    fingerprint = _fingerprint(
        settings=settings,
        bootstrap_start_date=bootstrap_start_date,
        panel_path=panel_path_obj,
        pipeline_output_dir=pipeline_output_path,
    )

    if from_stage and from_stage not in STAGES:
        raise ValueError(f"Unknown stage: {from_stage}")
    if stop_after and stop_after not in STAGES:
        raise ValueError(f"Unknown stage: {stop_after}")
    if resume:
        if not state:
            raise RuntimeError("Cannot resume: no previous e2e state found.")
        if state.get("fingerprint") != fingerprint:
            raise RuntimeError("Cannot resume: configuration or output paths changed since the previous run.")
        if state.get("status") == "completed":
            existing_status = _load_json(state_paths["status_json"])
            if existing_status:
                return existing_status

    start_index = 0
    if from_stage:
        start_index = STAGES.index(from_stage)
    elif resume and state.get("last_successful_stage") in STAGES:
        last_stage = state["last_successful_stage"]
        start_index = STAGES.index(last_stage) + 1
        if start_index >= len(STAGES):
            existing_status = _load_json(state_paths["status_json"])
            if existing_status:
                return existing_status
            start_index = len(STAGES) - 1

    prior_records = _load_stage_records(state.get("stage_records"))
    stage_records = [
        record for record in prior_records if record.stage in STAGES and STAGES.index(record.stage) < start_index
    ]
    guard_results = state.get("guard_results") or _empty_guard_results()
    run_started_at = state.get("run_started_at") if resume else None
    if not run_started_at:
        run_started_at = _utc_now()
    current_stage = "unknown"

    try:
        for stage in STAGES[start_index:]:
            current_stage = stage
            started_at = _utc_now()
            outputs: dict[str, Any] = {}
            command = None
            log_path = _write_stage_marker(
                settings,
                stage=stage,
                message=f"[stage-start] {stage} started_at={started_at}",
            )
            primary_output = None

            state.update(
                {
                    "fingerprint": fingerprint,
                    "run_started_at": run_started_at,
                    "current_stage": stage,
                    "status": "running",
                    "stage_records": [asdict(item) for item in stage_records],
                    "guard_results": guard_results,
                    "updated_at": _utc_now(),
                }
            )
            _write_json(state_paths["state"], state)

            if stage == "dependency_sync":
                log_path, command = _run_dependency_sync(settings)
            elif stage == "canonical_market_data":
                watermark = read_watermark(settings)
                if watermark is None:
                    run_bootstrap(settings=settings, start_date=bootstrap_start_date, end_date=today_utc().isoformat())
                else:
                    run_sync(settings=settings)
                dataset_manifest = _write_dataset_manifest(settings)
                primary_output = str(dataset_manifest_path(settings))
                outputs = {
                    "dataset_manifest_path": primary_output,
                    "dataset_build_id": dataset_manifest.get("dataset_build_id"),
                }
            elif stage == "verify_market_data":
                run_docs_sync_checks(base_ref=_DOCS_SYNC_BASE_REF)
                _set_guard_result(guard_results, guard="docs_sync_guard", result="passed", notes="Pre-export docs sync passed.")
                run_contract_checks(data_lake=str(settings.data_lake_root), config_dir=str(settings.configs_dir))
                _set_guard_result(guard_results, guard="schema_guard", result="passed", notes="Canonical contracts passed pre-export.")
                run_pit_checks(data_lake=str(settings.data_lake_root), config_dir=str(settings.configs_dir))
                _set_guard_result(guard_results, guard="pit_guard", result="passed", notes="PIT checks passed pre-export.")
                run_compat_guard()
                _set_guard_result(guard_results, guard="compat_guard", result="passed", notes="Canonical identity compat guard passed.")
                outputs = {"verified_guards": ["docs_sync_guard", "schema_guard", "pit_guard", "compat_guard"]}
            elif stage == "export_panel":
                watermark = read_watermark(settings)
                if watermark is None:
                    start_date = bootstrap_start_date
                    end_date = today_utc().isoformat()
                else:
                    start_date = str(watermark["start_date"])
                    end_date = str(watermark["end_date"])
                out = export_panel(
                    settings=settings,
                    output_path=str(panel_path_obj),
                    start_date=start_date,
                    end_date=end_date,
                )
                run_bridge_checks(
                    panel_path=str(out),
                    require_manifest=True,
                    data_lake=str(settings.data_lake_root),
                    config_dir=str(settings.configs_dir),
                )
                export_manifest = read_manifest(Path(str(out) + ".manifest.json"))
                primary_output = str(out)
                _set_guard_result(
                    guard_results,
                    guard="bridge_guard",
                    result="passed",
                    evidence_path=str(Path(str(out) + ".manifest.json")),
                    notes="Export bridge manifest and content checks passed.",
                )
                outputs = {
                    "panel_path": str(out),
                    "export_manifest_path": str(Path(str(out) + ".manifest.json")),
                    "dataset_build_id": export_manifest.get("dataset_build_id"),
                    "export_panel_version_id": export_manifest.get("export_panel_version_id"),
                }
            elif stage == "pipeline_run":
                pipeline_command = [
                    sys.executable,
                    str(_REPO_ROOT / "Pipeline.py"),
                    "--input_panel_csv",
                    str(panel_path_obj),
                    "--output_dir",
                    str(pipeline_output_path),
                ]
                resume_state = pipeline_output_path / "06_state" / "resume_state.json"
                if resume and resume_state.exists():
                    pipeline_command.append("--resume")
                command = " ".join(pipeline_command)
                log_path = _run_subprocess(pipeline_command, stage=stage, settings=settings)
                primary_output = str(pipeline_output_path)
                outputs = {"pipeline_output_dir": str(pipeline_output_path)}
            elif stage == "finalize_status":
                phase1_command = [
                    sys.executable,
                    str(_REPO_ROOT / "tools" / "phase1_sanity_check.py"),
                    "--output_dir",
                    str(pipeline_output_path),
                ]
                command = " ".join(phase1_command)
                log_path = _run_subprocess(phase1_command, stage=stage, settings=settings)
                verification_paths = _paths(settings)
                if _has_complete_pre_export_guard_evidence(guard_results):
                    _set_guard_result(
                        guard_results,
                        guard="verification_guard",
                        result="passed",
                        evidence_path=str(verification_paths["verification_json"]),
                        notes="Reused pre-export guard evidence; final bundle not rerun.",
                    )
                else:
                    verification_results = run_verification_bundle(
                        data_lake=str(settings.data_lake_root),
                        config_dir=str(settings.configs_dir),
                        panel_path=str(panel_path_obj),
                        base_ref=_DOCS_SYNC_BASE_REF,
                    )
                    _set_guard_result(
                        guard_results,
                        guard="verification_guard",
                        result="passed",
                        evidence_path=str(verification_paths["verification_json"]),
                        notes="Final integrated verification bundle passed.",
                    )
                    for guard, result in verification_results.items():
                        _set_guard_result(
                            guard_results,
                            guard=guard,
                            result=result,
                            notes="Confirmed by final verification bundle."
                            if guard != "verification_guard"
                            else "Final integrated verification bundle passed.",
                        )
                verification_json, verification_md = _write_verification_summary(settings, guard_results)
                primary_output = verification_json
                outputs = {
                    "phase1_sanity_check": "passed",
                    "verification_json": verification_json,
                    "verification_markdown": verification_md,
                }

            record = StageRecord(
                stage=stage,
                status="passed",
                started_at=started_at,
                finished_at=_utc_now(),
                command=command,
                log_path=log_path,
                primary_output=primary_output,
                outputs=outputs or None,
            )
            stage_records = [item for item in stage_records if item.stage != stage]
            stage_records.append(record)
            state.update(
                {
                    "fingerprint": fingerprint,
                    "run_started_at": run_started_at,
                    "current_stage": stage,
                    "last_successful_stage": stage,
                    "stage_records": [asdict(item) for item in stage_records],
                    "guard_results": guard_results,
                    "status": "running",
                    "updated_at": _utc_now(),
                    "last_failed_stage": None,
                    "blocker_classification": None,
                    "blocker_message": None,
                }
            )
            _write_json(state_paths["state"], state)

            if stop_after and stage == stop_after:
                _write_verification_summary(settings, guard_results)
                payload = _build_status_payload(
                    settings=settings,
                    stage_records=stage_records,
                    guard_results=guard_results,
                    status="partial_progress",
                    panel_path=panel_path_obj,
                    pipeline_output_dir=pipeline_output_path,
                    fingerprint=fingerprint,
                    run_started_at=run_started_at,
                    run_finished_at=_utc_now(),
                )
                _write_status_files(settings, payload)
                state["status"] = payload["status"]
                _write_json(state_paths["state"], state)
                return payload

        _write_verification_summary(settings, guard_results)
        payload = _build_status_payload(
            settings=settings,
            stage_records=stage_records,
            guard_results=guard_results,
            status="completed",
            panel_path=panel_path_obj,
            pipeline_output_dir=pipeline_output_path,
            fingerprint=fingerprint,
            run_started_at=run_started_at,
            run_finished_at=_utc_now(),
        )
        _write_status_files(settings, payload)
        state["status"] = payload["status"]
        _write_json(state_paths["state"], state)
        return payload
    except BaseException as exc:
        blocker_classification = _classify_blocker(exc)
        failed_stage = current_stage
        stage_records = [item for item in stage_records if item.stage != failed_stage]
        stage_records.append(
            StageRecord(
                stage=failed_stage,
                status="failed",
                started_at=_utc_now(),
                finished_at=_utc_now(),
                notes=str(exc),
            )
        )
        _write_verification_summary(settings, guard_results)
        payload = _build_status_payload(
            settings=settings,
            stage_records=stage_records,
            guard_results=guard_results,
            status="blocked_cleanly" if blocker_classification == "hard_blocker" else "partial_progress",
            panel_path=panel_path_obj,
            pipeline_output_dir=pipeline_output_path,
            fingerprint=fingerprint,
            run_started_at=run_started_at,
            run_finished_at=_utc_now(),
            blocker_classification=blocker_classification,
            blocker_message=str(exc),
        )
        _write_status_files(settings, payload)
        state.update(
            {
                "fingerprint": fingerprint,
                "run_started_at": run_started_at,
                "current_stage": failed_stage,
                "last_failed_stage": failed_stage,
                "stage_records": [asdict(item) for item in stage_records],
                "guard_results": guard_results,
                "status": payload["status"],
                "updated_at": _utc_now(),
                "blocker_classification": blocker_classification,
                "blocker_message": str(exc),
            }
        )
        _write_json(state_paths["state"], state)
        raise
