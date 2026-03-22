from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from control_plane.models import TaskClassification, TerminalState
from control_plane.policy_loader import (
    PolicyBootstrapError,
    compute_loader_manifest_hash,
    compute_policy_fingerprint_from_payload,
    load_bootstrapped_policy,
    load_canonical_policy_payload,
)
from control_plane.runtime_env import RuntimeEnvironmentError, ensure_repo_runtime, load_repo_secret
from control_plane.task_state import (
    append_state_transition,
    create_task_workspace,
    read_verifier_status,
    refresh_artifact_manifest,
    set_terminal_state,
    validate_task_scaffold,
    write_approval_record,
    write_review_output,
    write_verifier_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_bootstrap_pin(tmp_path: Path, fingerprint: str, loader_manifest_hash: str) -> Path:
    pin = tmp_path / "approved_bootstrap.json"
    pin.write_text(
        json.dumps(
            {
                "policy_fingerprint": fingerprint,
                "loader_manifest_hash": loader_manifest_hash,
            }
        ),
        encoding="utf-8",
    )
    return pin


def test_bootstrap_requires_combined_external_pin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_BOOTSTRAP_PIN_FILE", str(tmp_path / "missing.json"))
    monkeypatch.delenv("CODEX_POLICY_FINGERPRINT_FILE", raising=False)
    with pytest.raises(PolicyBootstrapError):
        load_bootstrapped_policy(PROJECT_ROOT)


def test_bootstrap_succeeds_with_matching_combined_pin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    fingerprint = compute_policy_fingerprint_from_payload(payload)
    loader_manifest_hash = compute_loader_manifest_hash(PROJECT_ROOT)
    pin_path = _write_bootstrap_pin(tmp_path, fingerprint, loader_manifest_hash)
    monkeypatch.setenv("CODEX_BOOTSTRAP_PIN_FILE", str(pin_path))
    policy = load_bootstrapped_policy(PROJECT_ROOT)
    assert policy.fingerprint == fingerprint
    assert policy.expected_loader_manifest_hash == loader_manifest_hash
    assert policy.bootstrap_pin_path == pin_path
    assert "approval_requirements.json" in policy.required_task_files()
    assert "review_outputs.json" in policy.required_task_files()


def test_repo_runtime_rejects_non_repo_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    runtime_policy = policy["runtime_environment"]
    monkeypatch.setattr("control_plane.runtime_env.platform.python_version", lambda: "3.12.10")
    monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")
    with pytest.raises(RuntimeEnvironmentError):
        ensure_repo_runtime(PROJECT_ROOT, runtime_policy)


def test_load_repo_secret_exports_expected_env(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    runtime_policy = policy["runtime_environment"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_API_KEY", "test-secret")
    loaded = load_repo_secret(PROJECT_ROOT, runtime_policy)
    assert loaded.source_label == "user_environment:CODEX_API_KEY"
    assert loaded.source_path is None
    assert "OPENAI_API_KEY" in loaded.exported_names
    assert "CODEX_API_KEY" in loaded.exported_names


def test_load_repo_secret_uses_legacy_file_when_env_is_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    policy = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    runtime_policy = dict(policy["runtime_environment"])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    secret_path = tmp_path / ".env" / "Codex_API_KEY"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text("legacy-secret\n", encoding="utf-8")

    loaded = load_repo_secret(tmp_path, runtime_policy)

    assert loaded.source_path == secret_path
    assert loaded.source_label == ".env/Codex_API_KEY"
    assert "OPENAI_API_KEY" in loaded.exported_names
    assert "CODEX_API_KEY" in loaded.exported_names


def test_task_workspace_creates_required_artifacts(tmp_path: Path) -> None:
    workspace = create_task_workspace(
        tmp_path,
        task_id="demo-task",
        goal="Demonstrate durable task scaffolding",
        classification=TaskClassification.BEHAVIOR_PRESERVING,
        policy_fingerprint="abc123",
    )
    missing = validate_task_scaffold(
        workspace,
        [
            "requirements.json",
            "acceptance.json",
            "agent_task.json",
            "task_brief.md",
            "classification.json",
            "summary.md",
            "handoff_state.json",
            "verification_checklist.json",
            "current_status.json",
            "final_result_summary.md",
            "warning_manifest.json",
            "environment_fingerprint.json",
            "trace_metadata.json",
            "execplan_reference.json",
            "approval_requirements.json",
            "review_outputs.json",
            "verifier_evidence.json",
            "state_log.jsonl",
            "artifact_manifest.json",
        ],
    )
    assert missing == []


def test_append_state_transition_updates_current_status(tmp_path: Path) -> None:
    workspace = create_task_workspace(
        tmp_path,
        task_id="state-task",
        goal="Track transitions",
        classification=TaskClassification.TEST_ONLY,
        policy_fingerprint="fingerprint",
    )
    append_state_transition(workspace, TerminalState.COMPLETED_WITH_WARNINGS, actor="Coordinator", detail="warn")
    status = json.loads(workspace.status_path.read_text(encoding="utf-8"))
    assert status["state"] == TerminalState.COMPLETED_WITH_WARNINGS.value
    assert status["detail"] == "warn"


def test_verifier_evidence_is_isolated_in_external_store(tmp_path: Path) -> None:
    workspace = create_task_workspace(
        tmp_path,
        task_id="verifier-task",
        goal="Write verifier evidence externally",
        classification=TaskClassification.BEHAVIOR_PRESERVING,
        policy_fingerprint="fingerprint",
    )
    write_verifier_evidence(workspace, success=True, checks={"tests": "passed"}, run_id="verifier-1")
    verifier_reference = json.loads(workspace.verifier_path.read_text(encoding="utf-8"))
    assert verifier_reference["store_relative_path"] == ".local/control_plane/verifier_runs/verifier-1/evidence.json"
    authoritative = read_verifier_status(workspace)
    assert authoritative["success"] is True
    assert authoritative["run_id"] == "verifier-1"
    assert authoritative["reference"]["store_hash"] == verifier_reference["store_hash"]


def test_completed_policy_changing_task_requires_reviews_and_approvals(tmp_path: Path) -> None:
    workspace = create_task_workspace(
        tmp_path,
        task_id="completed-task",
        goal="Require protected approvals",
        classification=TaskClassification.POLICY_CHANGING,
        policy_fingerprint="fingerprint",
    )
    write_verifier_evidence(workspace, success=True, checks={"tests": "passed"}, run_id="verifier-1")
    write_review_output(
        workspace,
        reviewer_role="Verifier",
        review_payload={"correctness_review": "pass", "regression_risk_review": "pass"},
    )
    with pytest.raises(ValueError):
        set_terminal_state(workspace, TerminalState.COMPLETED, actor="Coordinator", detail="done")

    write_review_output(
        workspace,
        reviewer_role="Auditor",
        review_payload={"unsupported_claim_review": "pass", "unsafe_command_pattern_review": "pass"},
    )
    write_approval_record(
        tmp_path,
        task_id=workspace.task_id,
        approval_class="requires_auditor",
        actor="auditor",
        note="Reviewed protected change",
        scope="control_plane",
    )
    write_approval_record(
        tmp_path,
        task_id=workspace.task_id,
        approval_class="requires_human",
        actor="user",
        note="Approved protected change",
        scope="control_plane",
    )
    set_terminal_state(workspace, TerminalState.COMPLETED, actor="Coordinator", detail="done")
    status = json.loads(workspace.status_path.read_text(encoding="utf-8"))
    assert status["state"] == TerminalState.COMPLETED.value


def test_refresh_artifact_manifest_records_external_artifacts(tmp_path: Path) -> None:
    workspace = create_task_workspace(
        tmp_path,
        task_id="manifest-task",
        goal="Record hashes",
        classification=TaskClassification.DOCS_ONLY,
        policy_fingerprint="fingerprint",
    )
    write_verifier_evidence(workspace, success=True, checks={"tests": "passed"}, run_id="verifier-1")
    write_approval_record(
        tmp_path,
        task_id=workspace.task_id,
        approval_class="requires_human",
        actor="user",
        note="Approved docs-only closure",
        scope="task",
    )
    refresh_artifact_manifest(
        workspace,
        project_root=tmp_path,
        policy_fingerprint="fingerprint",
        verifier_run_id="verifier-1",
        required_files=[path.name for path in workspace.tracked_paths()],
    )
    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert manifest["verifier_run_id"] == "verifier-1"
    assert manifest["external_artifacts"]["verifier_store_path"] == ".local/control_plane/verifier_runs/verifier-1/evidence.json"
    assert manifest["external_artifacts"]["approval_artifact_path"] == ".local/control_plane/approvals/manifest-task.json"


def test_phase1_change_check_fails_on_protected_surface_without_policy_changing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    fingerprint = compute_policy_fingerprint_from_payload(payload)
    loader_manifest_hash = compute_loader_manifest_hash(PROJECT_ROOT)
    pin_path = _write_bootstrap_pin(tmp_path, fingerprint, loader_manifest_hash)
    monkeypatch.setenv("CODEX_BOOTSTRAP_PIN_FILE", str(pin_path))
    result = subprocess.run(
        [
            sys.executable,
            "tools/control_plane.py",
            "phase1-change-check",
            "--classification",
            "docs_only",
            "--justification",
            "test",
            "--expected-file",
            "AGENTS.md",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["mismatch_check"] == "fail_protected_surface_without_policy_classification"
