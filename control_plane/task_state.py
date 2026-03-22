from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .models import TaskClassification, TaskWorkspace, TerminalState


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def atomic_write_json(path: Path, payload: object) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def current_git_commit(project_root: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def environment_fingerprint(project_root: Path) -> Mapping[str, Any]:
    return {
        "project_root": str(project_root.resolve()),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "created_at_utc": utc_now_iso(),
    }


def verifier_store_root(project_root: Path) -> Path:
    return project_root / ".local" / "control_plane" / "verifier_runs"


def approval_store_root(project_root: Path) -> Path:
    return project_root / ".local" / "control_plane" / "approvals"


def approval_record_path(project_root: Path, task_id: str) -> Path:
    return approval_store_root(project_root) / f"{task_id}.json"


def _safe_relative_path(project_root: Path, relative_path: str) -> Path:
    target = (project_root / relative_path).resolve()
    if project_root != target and project_root not in target.parents:
        raise ValueError(f"Path escapes project root: {relative_path}")
    return target


def _default_completion_approvals(classification: TaskClassification) -> list[str]:
    if classification in {TaskClassification.POLICY_CHANGING, TaskClassification.SPEC_CHANGING}:
        return ["requires_auditor", "requires_human"]
    return []


def _default_required_reviews(classification: TaskClassification) -> list[str]:
    if classification in {TaskClassification.POLICY_CHANGING, TaskClassification.SPEC_CHANGING}:
        return ["Verifier", "Auditor"]
    return ["Verifier"]


@dataclass(frozen=True)
class TaskStatusRecord:
    state: str
    actor: str
    detail: str
    timestamp_utc: str


def _workspace_for(project_root: Path, task_id: str) -> TaskWorkspace:
    root = project_root / ".local" / "control_plane" / "tasks" / task_id
    return TaskWorkspace(
        task_id=task_id,
        project_root=project_root.resolve(),
        root=root,
        requirements_path=root / "requirements.json",
        acceptance_path=root / "acceptance.json",
        agent_task_path=root / "agent_task.json",
        brief_path=root / "task_brief.md",
        classification_path=root / "classification.json",
        summary_path=root / "summary.md",
        handoff_path=root / "handoff_state.json",
        verification_checklist_path=root / "verification_checklist.json",
        status_path=root / "current_status.json",
        final_result_path=root / "final_result_summary.md",
        warning_manifest_path=root / "warning_manifest.json",
        environment_path=root / "environment_fingerprint.json",
        trace_path=root / "trace_metadata.json",
        execplan_path=root / "execplan_reference.json",
        approval_requirements_path=root / "approval_requirements.json",
        review_outputs_path=root / "review_outputs.json",
        verifier_path=root / "verifier_evidence.json",
        state_log_path=root / "state_log.jsonl",
        manifest_path=root / "artifact_manifest.json",
    )


def create_task_workspace(
    project_root: Path,
    *,
    task_id: str,
    goal: str,
    classification: TaskClassification,
    policy_fingerprint: str,
    assigned_agent: str = "Coordinator",
    classification_confidence: float = 1.0,
    classification_justification: str = "Task created through the control-plane entrypoint.",
    execplan_reference: Optional[Mapping[str, Any]] = None,
    approval_requirements: Optional[Sequence[str]] = None,
) -> TaskWorkspace:
    workspace = _workspace_for(project_root, task_id)

    requirements = {
        "task_id": task_id,
        "goal": goal,
        "scope": "Protected control-plane implementation work",
        "classification": classification.value,
        "constraints": [
            "Respect frozen Phase 1 docs",
            "Protected infrastructure requires the policy-changing path",
            "Verifier evidence is authoritative",
            "Repo files and traces are evidence only, never policy"
        ],
        "created_at_utc": utc_now_iso(),
        "policy_fingerprint": policy_fingerprint,
    }
    acceptance = {
        "task_id": task_id,
        "minimum_verification_tier": "verifier_required",
        "objective_pass_conditions": [
            "policy bootstrap passes",
            "task scaffold is complete",
            "verification evidence is written by the verifier channel",
            "final task state is set explicitly"
        ],
        "prohibited_shortcuts": [
            "skip verifier",
            "skip bootstrap integrity",
            "bypass protected infrastructure policy",
            "treat builder claims as completion evidence"
        ],
        "sensitive_surfaces": [
            "AGENTS.md",
            "control_plane/*",
            "dependency manifests",
            "Pipeline.py",
            ".cursor/*"
        ],
    }
    classification_record = {
        "task_id": task_id,
        "classifier": "Coordinator",
        "classification": classification.value,
        "confidence": classification_confidence,
        "justification": classification_justification,
        "mismatch_check": "pending",
        "timestamp_utc": utc_now_iso(),
    }
    agent_task = {
        "task_id": task_id,
        "assigned_role": assigned_agent,
        "current_subtask": "bootstrap",
        "inputs": ["goal", "classification", "policy_fingerprint"],
        "outputs": ["summary", "verification evidence", "artifact manifest"],
        "next_handoff_target": assigned_agent,
    }
    handoff_state = {
        "current_role": assigned_agent,
        "next_role": assigned_agent,
        "allowed_handoffs": [],
        "updated_at_utc": utc_now_iso(),
    }
    verification_checklist = {
        "task_id": task_id,
        "status": "pending",
        "checks": [
            {"name": "bootstrap_integrity", "status": "pending"},
            {"name": "task_scaffold_complete", "status": "pending"},
            {"name": "verifier_evidence", "status": "pending"},
            {"name": "terminal_state", "status": "pending"}
        ],
        "updated_at_utc": utc_now_iso(),
    }
    warning_manifest = {"task_id": task_id, "warnings": [], "updated_at_utc": utc_now_iso()}
    approval_payload = {
        "task_id": task_id,
        "required_for_completion": list(approval_requirements or _default_completion_approvals(classification)),
        "required_reviews": _default_required_reviews(classification),
        "updated_at_utc": utc_now_iso(),
    }
    review_outputs = {"task_id": task_id, "reviews": {}, "updated_at_utc": utc_now_iso()}
    verifier_evidence = {
        "task_id": task_id,
        "status": "pending",
        "run_id": None,
        "store_relative_path": None,
        "store_hash": None,
        "timestamp_utc": None,
    }
    trace_metadata = {
        "task_id": task_id,
        "group_id": None,
        "trace_mode": "minimal",
        "metadata": {},
        "updated_at_utc": utc_now_iso(),
    }
    execplan_payload = {
        "task_id": task_id,
        "plans_file": "PLANS.md",
        "reference": dict(execplan_reference or {}),
        "updated_at_utc": utc_now_iso(),
    }

    atomic_write_json(workspace.requirements_path, requirements)
    atomic_write_json(workspace.acceptance_path, acceptance)
    atomic_write_json(workspace.agent_task_path, agent_task)
    atomic_write_json(workspace.classification_path, classification_record)
    atomic_write_json(workspace.handoff_path, handoff_state)
    atomic_write_json(workspace.verification_checklist_path, verification_checklist)
    atomic_write_json(workspace.warning_manifest_path, warning_manifest)
    atomic_write_json(workspace.environment_path, environment_fingerprint(project_root))
    atomic_write_json(workspace.trace_path, trace_metadata)
    atomic_write_json(workspace.execplan_path, execplan_payload)
    atomic_write_json(workspace.approval_requirements_path, approval_payload)
    atomic_write_json(workspace.review_outputs_path, review_outputs)
    atomic_write_json(workspace.verifier_path, verifier_evidence)
    atomic_write_text(
        workspace.brief_path,
        "# Task Brief\n\n"
        f"- Goal: {goal}\n"
        f"- Classification: `{classification.value}`\n"
        f"- Assigned role: `{assigned_agent}`\n",
    )
    atomic_write_text(
        workspace.summary_path,
        "# Current Decision Summary\n\n"
        f"- Goal: {goal}\n"
        f"- Classification: `{classification.value}`\n"
        "- Current decision: bootstrap complete, begin guarded execution.\n"
        "- Next exact action: run the coordinator under canonical policy.\n",
    )
    atomic_write_text(
        workspace.final_result_path,
        "# Final Result Summary\n\nTask is still in progress.\n",
    )
    append_state_transition(workspace, TerminalState.PARTIAL_PROGRESS, actor="Coordinator", detail="Task scaffold created")
    refresh_artifact_manifest(
        workspace,
        project_root=project_root,
        policy_fingerprint=policy_fingerprint,
        verifier_run_id=None,
        required_files=[path.name for path in workspace.tracked_paths()],
    )
    return workspace


def append_state_transition(workspace: TaskWorkspace, state: TerminalState, *, actor: str, detail: str) -> None:
    record = TaskStatusRecord(
        state=state.value,
        actor=actor,
        detail=detail,
        timestamp_utc=utc_now_iso(),
    )
    workspace.root.mkdir(parents=True, exist_ok=True)
    with workspace.state_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    atomic_write_json(workspace.status_path, asdict(record))


def read_current_status(workspace: TaskWorkspace) -> Mapping[str, Any]:
    if not workspace.status_path.exists():
        return {}
    return json.loads(workspace.status_path.read_text(encoding="utf-8"))


def read_verifier_status(workspace: TaskWorkspace) -> Mapping[str, Any]:
    if not workspace.verifier_path.exists():
        return {}
    reference = json.loads(workspace.verifier_path.read_text(encoding="utf-8"))
    relative_path = reference.get("store_relative_path")
    expected_hash = reference.get("store_hash")
    if not relative_path:
        return reference
    store_path = _safe_relative_path(workspace.project_root, str(relative_path))
    if not store_path.exists():
        raise FileNotFoundError(f"Verifier store artifact is missing: {store_path}")
    actual_hash = file_sha256(store_path)
    if expected_hash != actual_hash:
        raise ValueError(
            f"Verifier artifact hash mismatch for task {workspace.task_id}: expected {expected_hash}, got {actual_hash}"
        )
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Verifier artifact is not a JSON object: {store_path}")
    merged = dict(payload)
    merged["reference"] = reference
    return merged


def read_approval_requirements(workspace: TaskWorkspace) -> Mapping[str, Any]:
    if not workspace.approval_requirements_path.exists():
        return {}
    return json.loads(workspace.approval_requirements_path.read_text(encoding="utf-8"))


def read_review_outputs(workspace: TaskWorkspace) -> Mapping[str, Any]:
    if not workspace.review_outputs_path.exists():
        return {}
    return json.loads(workspace.review_outputs_path.read_text(encoding="utf-8"))


def read_approval_record(project_root: Path, task_id: str) -> Mapping[str, Any]:
    path = approval_record_path(project_root, task_id)
    if not path.exists():
        return {"task_id": task_id, "approvals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Approval artifact is not a JSON object: {path}")
    return payload


def write_classification_record(
    workspace: TaskWorkspace,
    *,
    classifier: str,
    classification: str,
    confidence: float,
    justification: str,
    mismatch_check: str,
) -> None:
    atomic_write_json(
        workspace.classification_path,
        {
            "task_id": workspace.task_id,
            "classifier": classifier,
            "classification": classification,
            "confidence": confidence,
            "justification": justification,
            "mismatch_check": mismatch_check,
            "timestamp_utc": utc_now_iso(),
        },
    )


def write_decision_summary(workspace: TaskWorkspace, markdown: str) -> None:
    atomic_write_text(workspace.summary_path, markdown.rstrip() + "\n")


def write_handoff_state(
    workspace: TaskWorkspace,
    *,
    current_role: str,
    next_role: str,
    allowed_handoffs: Sequence[str],
    note: str,
) -> None:
    atomic_write_json(
        workspace.handoff_path,
        {
            "task_id": workspace.task_id,
            "current_role": current_role,
            "next_role": next_role,
            "allowed_handoffs": list(allowed_handoffs),
            "note": note,
            "updated_at_utc": utc_now_iso(),
        },
    )


def write_verification_checklist(
    workspace: TaskWorkspace,
    *,
    checks: Sequence[Mapping[str, Any]],
    status: str,
) -> None:
    atomic_write_json(
        workspace.verification_checklist_path,
        {
            "task_id": workspace.task_id,
            "status": status,
            "checks": [dict(item) for item in checks],
            "updated_at_utc": utc_now_iso(),
        },
    )


def write_warning_manifest(workspace: TaskWorkspace, warnings: Sequence[Mapping[str, Any] | str]) -> None:
    normalized: list[Any] = []
    for item in warnings:
        if isinstance(item, Mapping):
            normalized.append(dict(item))
        else:
            normalized.append({"message": str(item)})
    atomic_write_json(
        workspace.warning_manifest_path,
        {"task_id": workspace.task_id, "warnings": normalized, "updated_at_utc": utc_now_iso()},
    )


def write_review_output(
    workspace: TaskWorkspace,
    *,
    reviewer_role: str,
    review_payload: Mapping[str, Any],
) -> None:
    current = read_review_outputs(workspace)
    reviews = dict(current.get("reviews", {}))
    reviews[reviewer_role] = {
        "payload": dict(review_payload),
        "updated_at_utc": utc_now_iso(),
    }
    atomic_write_json(
        workspace.review_outputs_path,
        {"task_id": workspace.task_id, "reviews": reviews, "updated_at_utc": utc_now_iso()},
    )


def write_trace_metadata(workspace: TaskWorkspace, *, group_id: str, metadata: Mapping[str, Any], trace_mode: str) -> None:
    atomic_write_json(
        workspace.trace_path,
        {
            "task_id": workspace.task_id,
            "group_id": group_id,
            "trace_mode": trace_mode,
            "metadata": dict(metadata),
            "updated_at_utc": utc_now_iso(),
        },
    )


def write_final_result_summary(workspace: TaskWorkspace, markdown: str) -> None:
    atomic_write_text(workspace.final_result_path, markdown.rstrip() + "\n")


def write_verifier_evidence(workspace: TaskWorkspace, *, success: bool, checks: Mapping[str, Any], run_id: str) -> None:
    store_root = verifier_store_root(workspace.project_root)
    store_path = store_root / run_id / "evidence.json"
    payload = {
        "task_id": workspace.task_id,
        "success": success,
        "checks": dict(checks),
        "run_id": run_id,
        "timestamp_utc": utc_now_iso(),
    }
    atomic_write_json(store_path, payload)
    relative_store_path = str(store_path.relative_to(workspace.project_root)).replace("\\", "/")
    atomic_write_json(
        workspace.verifier_path,
        {
            "task_id": workspace.task_id,
            "status": "written",
            "run_id": run_id,
            "store_relative_path": relative_store_path,
            "store_hash": file_sha256(store_path),
            "timestamp_utc": utc_now_iso(),
        },
    )
    write_review_output(workspace, reviewer_role="Verifier", review_payload=payload)


def write_approval_record(
    project_root: Path,
    *,
    task_id: str,
    approval_class: str,
    actor: str,
    note: str,
    scope: str,
) -> Path:
    path = approval_record_path(project_root, task_id)
    current = read_approval_record(project_root, task_id)
    approvals = list(current.get("approvals", []))
    approvals.append(
        {
            "approval_class": approval_class,
            "actor": actor,
            "note": note,
            "scope": scope,
            "timestamp_utc": utc_now_iso(),
        }
    )
    atomic_write_json(path, {"task_id": task_id, "approvals": approvals, "updated_at_utc": utc_now_iso()})
    return path


def _has_required_reviews(workspace: TaskWorkspace, required_reviews: Sequence[str]) -> list[str]:
    reviews = read_review_outputs(workspace).get("reviews", {})
    missing: list[str] = []
    for reviewer_role in required_reviews:
        if reviewer_role not in reviews:
            missing.append(reviewer_role)
    return missing


def _has_required_approvals(workspace: TaskWorkspace, required_classes: Sequence[str]) -> list[str]:
    approvals = read_approval_record(workspace.project_root, workspace.task_id).get("approvals", [])
    granted = {
        str(item.get("approval_class"))
        for item in approvals
        if isinstance(item, Mapping) and item.get("approval_class")
    }
    return [approval for approval in required_classes if approval not in granted]


def validate_task_scaffold(workspace: TaskWorkspace, required_files: Sequence[str]) -> list[str]:
    missing: list[str] = []
    for name in required_files:
        target = workspace.root / name
        if not target.exists():
            missing.append(name)
    return missing


def set_terminal_state(
    workspace: TaskWorkspace,
    state: TerminalState,
    *,
    actor: str,
    detail: str,
    warning_manifest: Optional[Sequence[Mapping[str, Any] | str]] = None,
) -> None:
    verifier_status = read_verifier_status(workspace)
    verifier_success = verifier_status.get("success")
    approval_requirements = read_approval_requirements(workspace)
    required_approvals = [str(item) for item in approval_requirements.get("required_for_completion", [])]
    required_reviews = [str(item) for item in approval_requirements.get("required_reviews", [])]
    if state in {TerminalState.COMPLETED, TerminalState.COMPLETED_WITH_WARNINGS} and verifier_success is not True:
        raise ValueError("Completed states require verifier success evidence")
    if state in {TerminalState.COMPLETED, TerminalState.COMPLETED_WITH_WARNINGS}:
        missing_reviews = _has_required_reviews(workspace, required_reviews)
        if missing_reviews:
            raise ValueError("Completed states require structured review outputs from: " + ", ".join(missing_reviews))
        missing_approvals = _has_required_approvals(workspace, required_approvals)
        if missing_approvals:
            raise ValueError("Completed states require approval artifacts: " + ", ".join(missing_approvals))
    if state is TerminalState.COMPLETED_WITH_WARNINGS:
        if not warning_manifest:
            raise ValueError("completed_with_warnings requires a warning manifest")
        write_warning_manifest(workspace, warning_manifest)
    if state is TerminalState.BLOCKED_CLEANLY and not detail.strip():
        raise ValueError("blocked_cleanly requires a blocker detail")
    append_state_transition(workspace, state, actor=actor, detail=detail)
    write_final_result_summary(
        workspace,
        "# Final Result Summary\n\n"
        f"- Terminal state: `{state.value}`\n"
        f"- Actor: `{actor}`\n"
        f"- Detail: {detail}\n",
    )


def refresh_artifact_manifest(
    workspace: TaskWorkspace,
    *,
    project_root: Path,
    policy_fingerprint: str,
    verifier_run_id: Optional[str],
    required_files: Sequence[str],
) -> None:
    missing_files = validate_task_scaffold(workspace, required_files)
    if workspace.manifest_path.name in missing_files:
        missing_files.remove(workspace.manifest_path.name)
    tracked_files = [path for path in workspace.tracked_paths() if path.exists()]
    verifier_reference = json.loads(workspace.verifier_path.read_text(encoding="utf-8")) if workspace.verifier_path.exists() else {}
    verifier_store_relative = verifier_reference.get("store_relative_path")
    verifier_store_hash = verifier_reference.get("store_hash")
    approval_path = approval_record_path(project_root, workspace.task_id)
    manifest = {
        "task_id": workspace.task_id,
        "policy_fingerprint": policy_fingerprint,
        "git_commit": current_git_commit(project_root),
        "verifier_run_id": verifier_run_id,
        "generated_at_utc": utc_now_iso(),
        "required_files": list(required_files),
        "missing_files": missing_files,
        "files": {
            str(path.relative_to(workspace.root)): file_sha256(path)
            for path in tracked_files
        },
        "external_artifacts": {
            "verifier_store_path": verifier_store_relative,
            "verifier_store_hash": verifier_store_hash,
            "approval_artifact_path": str(approval_path.relative_to(project_root)).replace("\\", "/") if approval_path.exists() else None,
            "approval_artifact_hash": file_sha256(approval_path) if approval_path.exists() else None,
        },
    }
    atomic_write_json(workspace.manifest_path, manifest)
