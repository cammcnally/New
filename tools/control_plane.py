from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

SUPPORTED_PYTHON_MIN = (3, 11, 9)
SUPPORTED_PYTHON_MAX_EXCLUSIVE = (3, 12, 0)


def _require_supported_python_version(version_info: tuple[int, int, int] | None = None) -> None:
    current = tuple(version_info or tuple(sys.version_info[:3]))
    if current < SUPPORTED_PYTHON_MIN or current >= SUPPORTED_PYTHON_MAX_EXCLUSIVE:
        current_text = ".".join(str(part) for part in current)
        min_text = ".".join(str(part) for part in SUPPORTED_PYTHON_MIN)
        max_text = ".".join(str(part) for part in SUPPORTED_PYTHON_MAX_EXCLUSIVE[:2])
        raise SystemExit(
            "Unsupported Python interpreter for this repository: "
            f"{current_text}. Use >={min_text},<{max_text} from the workspace virtual environment."
        )


_require_supported_python_version()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) in sys.path:
    sys.path.remove(str(TOOLS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.codex_mcp import CodexMCPBackend
from control_plane.models import TaskClassification
from control_plane.orchestrator import CodexControlPlane
from control_plane.policy_loader import load_bootstrapped_policy, load_canonical_policy_payload, trust_current_policy
from control_plane.runtime_env import ensure_repo_runtime, load_repo_secret, resolve_git_executable
from control_plane.task_state import write_approval_record
from tools.refresh_bootstrap_locks import refresh_bootstrap_locks


def _matches_protected_path(candidate_path: str, protected_path: str) -> bool:
    candidate = candidate_path.replace("\\", "/").strip("/")
    protected = protected_path.replace("\\", "/").strip("/")
    if protected.endswith("*"):
        return candidate.startswith(protected[:-1].rstrip("/"))
    return candidate == protected or candidate.startswith(protected.rstrip("/") + "/")


def _load_policy(*, require_external_pin: bool, require_runtime_env: bool) -> object:
    policy = load_bootstrapped_policy(PROJECT_ROOT, require_external_pin=require_external_pin)
    if require_runtime_env:
        ensure_repo_runtime(PROJECT_ROOT, policy.runtime_environment)
        load_repo_secret(PROJECT_ROOT, policy.runtime_environment)
    return policy


def _collect_repo_changes() -> list[str]:
    git_executable = resolve_git_executable(PROJECT_ROOT)
    result = subprocess.run(
        [git_executable, "status", "--short"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    changed: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        changed.append(line[3:].strip().replace("\\", "/"))
    return changed


def cmd_trust_policy(_: argparse.Namespace) -> int:
    destination = trust_current_policy(PROJECT_ROOT)
    bootstrap_lock, policy_lock = refresh_bootstrap_locks(PROJECT_ROOT)
    print(
        json.dumps(
            {
                "trusted_bootstrap_pin": str(destination),
                "bootstrap_lock": str(bootstrap_lock),
                "policy_lock": str(policy_lock),
            },
            indent=2,
        )
    )
    return 0


def cmd_show_policy(_: argparse.Namespace) -> int:
    policy = _load_policy(require_external_pin=False, require_runtime_env=False)
    print(
        json.dumps(
            {
                "fingerprint": policy.fingerprint,
                "policy_version": policy.raw_policy.get("policy_version"),
                "bootstrap_pin_path": str(policy.bootstrap_pin_path) if policy.bootstrap_pin_path else None,
            },
            indent=2,
        )
    )
    return 0


def cmd_validate_bootstrap(_: argparse.Namespace) -> int:
    policy = _load_policy(require_external_pin=True, require_runtime_env=False)
    print(
        json.dumps(
            {
                "policy_path": str(policy.policy_path),
                "fingerprint": policy.fingerprint,
                "loader_manifest_hash": policy.expected_loader_manifest_hash,
                "bootstrap_pin_path": str(policy.bootstrap_pin_path) if policy.bootstrap_pin_path else None,
            },
            indent=2,
        )
    )
    return 0


def cmd_list_codex_tools(_: argparse.Namespace) -> int:
    policy = _load_policy(require_external_pin=True, require_runtime_env=True)
    expected_tools = [str(item) for item in policy.mcp_policy.get("expected_tools", [])]
    with CodexMCPBackend(PROJECT_ROOT) as backend:
        available = backend.ensure_expected_tools(expected_tools)
    print(json.dumps({"expected_tools": expected_tools, "available_tools": available}, indent=2))
    return 0


def cmd_phase1_change_check(args: argparse.Namespace) -> int:
    policy = _load_policy(require_external_pin=True, require_runtime_env=False)
    classification = TaskClassification(args.classification)
    infra = policy.protected_infrastructure
    flat = infra.get("paths", [])
    if not flat:
        flat = list(infra.get("control_plane_paths", [])) + list(infra.get("phase1_authority_paths", []))
    protected_paths = [str(p) for p in flat]
    expected_files = list(args.expected_file)
    if not expected_files:
        expected_files = _collect_repo_changes()
    touches_protected = any(
        any(_matches_protected_path(expected, protected) for protected in protected_paths)
        for expected in expected_files
    )
    if classification is TaskClassification.POLICY_CHANGING:
        mismatch_check = "pass" if touches_protected else "warn_no_protected_match"
    elif touches_protected:
        mismatch_check = "fail_protected_surface_without_policy_classification"
    else:
        mismatch_check = "pass"
    payload = {
        "classifier": "Coordinator",
        "classification": classification.value,
        "confidence": args.confidence,
        "justification": args.justification,
        "expected_files": expected_files,
        "mismatch_check": mismatch_check,
        "policy_fingerprint": policy.fingerprint,
    }
    print(json.dumps(payload, indent=2))
    return 2 if mismatch_check.startswith("fail_") else 0


def cmd_run_task(args: argparse.Namespace) -> int:
    _load_policy(require_external_pin=True, require_runtime_env=True)
    control_plane = CodexControlPlane(PROJECT_ROOT)
    result = asyncio.run(
        control_plane.run_task(
            task_id=args.task_id,
            goal=args.goal,
            classification=TaskClassification(args.classification),
        )
    )
    final_output = getattr(result, "final_output", None)
    print(final_output if final_output is not None else str(result))
    return 0


def cmd_read_pipeline_log(args: argparse.Namespace) -> int:
    _load_policy(require_external_pin=True, require_runtime_env=False)
    target = (PROJECT_ROOT / args.output_dir / "00_logs" / "pipeline.log").resolve()
    if PROJECT_ROOT not in target.parents:
        raise SystemExit("Resolved pipeline log escapes project root")
    if not target.exists():
        print(json.dumps({"path": str(target), "exists": False, "tail": []}, indent=2))
        return 0
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    print(json.dumps({"path": str(target), "exists": True, "tail": lines[-max(args.tail_lines, 1) :]}, indent=2))
    return 0


def cmd_show_registries(_: argparse.Namespace) -> int:
    policy = _load_policy(require_external_pin=True, require_runtime_env=False)
    print(json.dumps(policy.governance_registries, indent=2, sort_keys=True))
    return 0


def cmd_render_cursor_projection(_: argparse.Namespace) -> int:
    _load_policy(require_external_pin=True, require_runtime_env=False)
    from control_plane.cursor_projection import render_cursor_projection

    created = render_cursor_projection(PROJECT_ROOT)
    print(json.dumps({"rendered_files": [str(path.relative_to(PROJECT_ROOT)) for path in created]}, indent=2))
    return 0


def cmd_record_approval(args: argparse.Namespace) -> int:
    _load_policy(require_external_pin=True, require_runtime_env=False)
    artifact = write_approval_record(
        PROJECT_ROOT,
        task_id=args.task_id,
        approval_class=args.approval_class,
        actor=args.actor,
        note=args.note,
        scope=args.scope,
    )
    print(json.dumps({"task_id": args.task_id, "approval_artifact": str(artifact)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified Codex control plane entrypoint")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trust_policy = subparsers.add_parser("trust-policy", help="Write the combined bootstrap pin for the current canonical policy and loader manifest")
    trust_policy.set_defaults(func=cmd_trust_policy)

    show_policy = subparsers.add_parser("show-policy", help="Show the current policy fingerprint without requiring a trusted pin")
    show_policy.set_defaults(func=cmd_show_policy)

    validate_bootstrap = subparsers.add_parser("validate-bootstrap", help="Validate bootstrap integrity and trusted policy fingerprint")
    validate_bootstrap.set_defaults(func=cmd_validate_bootstrap)

    list_codex_tools = subparsers.add_parser("list-codex-tools", help="List tools exposed by the local Codex MCP server")
    list_codex_tools.set_defaults(func=cmd_list_codex_tools)

    phase1_check = subparsers.add_parser("phase1-change-check", help="Emit a structured classification artifact")
    phase1_check.add_argument("--classification", required=True, choices=[item.value for item in TaskClassification])
    phase1_check.add_argument("--confidence", type=float, default=0.5)
    phase1_check.add_argument("--justification", required=True)
    phase1_check.add_argument("--expected-file", action="append", default=[])
    phase1_check.set_defaults(func=cmd_phase1_change_check)

    run_task = subparsers.add_parser("run-task", help="Run a traced orchestrator task")
    run_task.add_argument("--task-id", required=True)
    run_task.add_argument("--goal", required=True)
    run_task.add_argument("--classification", required=True, choices=[item.value for item in TaskClassification])
    run_task.set_defaults(func=cmd_run_task)

    read_pipeline_log = subparsers.add_parser("read-pipeline-log", help="Read the authoritative pipeline log tail")
    read_pipeline_log.add_argument("--output-dir", default="pipeline_outputs")
    read_pipeline_log.add_argument("--tail-lines", type=int, default=80)
    read_pipeline_log.set_defaults(func=cmd_read_pipeline_log)

    show_registries = subparsers.add_parser("show-governance-registries", help="Show the loaded governance registries")
    show_registries.set_defaults(func=cmd_show_registries)

    render_cursor = subparsers.add_parser("render-cursor-projection", help="Render local .cursor compatibility shims")
    render_cursor.set_defaults(func=cmd_render_cursor_projection)

    record_approval = subparsers.add_parser("record-approval", help="Record an approval artifact for a task")
    record_approval.add_argument("--task-id", required=True)
    record_approval.add_argument(
        "--approval-class",
        required=True,
        choices=["requires_verifier", "requires_auditor", "requires_human"],
    )
    record_approval.add_argument("--actor", required=True)
    record_approval.add_argument("--note", required=True)
    record_approval.add_argument("--scope", default="task")
    record_approval.set_defaults(func=cmd_record_approval)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
