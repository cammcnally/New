from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.pass_contract_common import (
    collect_final_report_errors,
    collect_scope_errors,
    current_governed_changes,
    get_pass_contract_paths,
    latest_history_record,
    load_active_issue,
    load_json,
    load_pass_contract_policy,
    load_pass_contract_template,
    staged_governed_changes,
)
from tools.repo_authority_common import load_repo_authority_registry, normalize_path

POLICY_SURFACES = (
    "docs/governance/AGENT_PASS_CONTRACT.md",
    "config/canonical/pass_contract_policy.json",
    "config/canonical/pass_contract_report_template.json",
    "tools/pass_contract_common.py",
    "tools/pass_contract.py",
    "tools/verify_pass_contract.py",
    "tests/test_pass_contract.py",
    "tests/acceptance/test_pass_contract_wiring.py",
    ".pre-commit-config.yaml",
    ".cursor/rules/agent-code-self-review.mdc",
)


def collect_policy_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    errors: list[str] = []
    policy = load_pass_contract_policy(project_root)
    template = load_pass_contract_template(project_root, policy)

    for relative in POLICY_SURFACES:
        if not (project_root / relative).exists():
            errors.append(f"missing required pass-contract surface: {relative}")

    required_fields = list(policy["required_fields"])
    missing_template_fields = [field for field in required_fields if field not in template]
    if missing_template_fields:
        errors.append(
            "pass contract template missing required fields: " + ", ".join(missing_template_fields)
        )
    for field in ("acceptance_criteria_results", "baseline_snapshot", "final_gate_reason", "report_status"):
        if field not in template:
            errors.append(f"pass contract template missing expected support field: {field}")

    repo_authority_text = (project_root / "config" / "canonical" / "repo_authority.yaml").read_text(encoding="utf-8")
    for snippet in (
        "docs/governance/AGENT_PASS_CONTRACT.md",
        "config/canonical/pass_contract_policy.json",
        "config/canonical/pass_contract_report_template.json",
        ".pre-commit-config.yaml",
    ):
        if snippet not in repo_authority_text:
            errors.append(f"repo authority registry missing pass-contract snippet: {snippet}")

    policy_doc_text = (project_root / "docs" / "governance" / "REPO_AUTHORITY_POLICY.md").read_text(encoding="utf-8")
    for snippet in (
        "docs/governance/AGENT_PASS_CONTRACT.md",
        "config/canonical/pass_contract_policy.json",
        "config/canonical/pass_contract_report_template.json",
        "tools/verify_pass_contract.py",
        "tests/acceptance/test_pass_contract_wiring.py",
    ):
        if snippet not in policy_doc_text:
            errors.append(f"repo authority policy missing pass-contract reference: {snippet}")

    makefile_text = (project_root / "Makefile").read_text(encoding="utf-8")
    for snippet in (
        "verify-pass-contract:",
        "uv run python tools/verify_pass_contract.py --policy-only",
        "tests/acceptance/test_pass_contract_wiring.py",
    ):
        if snippet not in makefile_text:
            errors.append(f"Makefile missing pass-contract wiring: {snippet}")

    workflow_text = (project_root / ".github" / "workflows" / "repo-governance.yml").read_text(encoding="utf-8")
    for snippet in (
        "uv run python tools/verify_pass_contract.py --policy-only",
        "uv run python -m pytest tests/acceptance/test_pass_contract_wiring.py -q",
    ):
        if snippet not in workflow_text:
            errors.append(f"repo-governance workflow missing pass-contract step: {snippet}")

    pre_commit_text = (project_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    for snippet in (
        "id: verify-pass-contract-pre-commit",
        "uv run python tools/verify_pass_contract.py --pre-commit",
        "id: verify-pass-contract-pre-push",
        "uv run python tools/verify_pass_contract.py --pre-push",
    ):
        if snippet not in pre_commit_text:
            errors.append(f".pre-commit-config.yaml missing pass-contract hook: {snippet}")

    hook_payload = json.loads((project_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    session_start = hook_payload.get("hooks", {}).get("SessionStart", [])
    if not _hook_command_exists(session_start, "uv run python tools/verify_pass_contract.py --session-start"):
        errors.append(".codex/hooks.json missing SessionStart pass-contract gate")

    projection_text = (project_root / "control_plane" / "cursor_projection.py").read_text(encoding="utf-8")
    for snippet in (
        "docs/governance/AGENT_PASS_CONTRACT.md",
        "tools/pass_contract.py start",
        "tools/pass_contract.py close",
    ):
        if snippet not in projection_text:
            errors.append(f"cursor projection missing pass-contract compatibility surface: {snippet}")

    return sorted(dict.fromkeys(errors))


def _hook_command_exists(session_start_entries: object, command: str) -> bool:
    if not isinstance(session_start_entries, list):
        return False
    for matcher_entry in session_start_entries:
        if not isinstance(matcher_entry, dict):
            continue
        hooks = matcher_entry.get("hooks", [])
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False


def collect_active_report_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    paths = get_pass_contract_paths(project_root, policy)

    active = load_active_issue(paths)
    if active is None:
        dirty = current_governed_changes(project_root, registry)
        if dirty:
            return [f"governed changes exist without an active pass contract: {dirty}"]
        return []

    report_relative = active.get("report_path")
    if not isinstance(report_relative, str) or not report_relative.strip():
        return ["active issue state missing report_path"]
    report_path = project_root / report_relative
    if not report_path.exists():
        return [f"active report path does not exist: {report_relative}"]
    report = load_json(report_path)
    errors = collect_scope_errors(report, policy, registry)
    if report.get("final_gate_decision"):
        errors.extend(
            collect_final_report_errors(
                report,
                policy,
                registry,
                report_path=normalize_path(report_path.relative_to(project_root)),
            )
        )
    return sorted(dict.fromkeys(errors))


def collect_pre_commit_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    paths = get_pass_contract_paths(project_root, policy)
    staged = staged_governed_changes(project_root, registry)
    if not staged:
        return []

    active = load_active_issue(paths)
    if active is None:
        return [f"staged governed files require an active pass contract: {staged}"]

    report_path = project_root / str(active.get("report_path", ""))
    if not report_path.exists():
        return [f"active report path does not exist: {active.get('report_path')}"]
    report = load_json(report_path)
    errors = collect_scope_errors(report, policy, registry)
    planned = set(report.get("planned_files", []))
    unexpected = sorted(set(staged) - planned)
    if unexpected:
        errors.append(f"staged files fall outside planned_files: {unexpected}")
    return sorted(dict.fromkeys(errors))


def collect_pre_push_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    paths = get_pass_contract_paths(project_root, policy)

    active = load_active_issue(paths)
    if active is not None:
        return [f"pre-push blocked while active issue remains open: {active.get('issue_id')}"]

    latest = latest_history_record(paths)
    if latest is None:
        return ["pre-push blocked because no closed pass-contract report exists yet"]

    report_relative = latest.get("report_path")
    if not isinstance(report_relative, str) or not report_relative.strip():
        return ["latest pass-contract history entry missing report_path"]
    report_path = project_root / report_relative
    if not report_path.exists():
        return [f"latest pass-contract report does not exist: {report_relative}"]

    report = load_json(report_path)
    errors = collect_final_report_errors(
        report,
        policy,
        registry,
        report_path=normalize_path(report_path.relative_to(project_root)),
    )
    if report.get("report_status") != "closed":
        errors.append("pre-push requires the latest pass-contract report to be closed")
    if latest.get("final_gate_decision") != "GO FOR NEXT ISSUE":
        errors.append(
            "pre-push requires the latest closed pass-contract report to end with GO FOR NEXT ISSUE"
        )
    return sorted(dict.fromkeys(errors))


def collect_session_start_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    paths = get_pass_contract_paths(project_root, policy)

    active = load_active_issue(paths)
    if active is not None:
        report_path = project_root / str(active.get("report_path", ""))
        if not report_path.exists():
            return [f"active report path does not exist: {active.get('report_path')}"]
        report = load_json(report_path)
        return sorted(dict.fromkeys(collect_scope_errors(report, policy, registry)))

    latest = latest_history_record(paths)
    if latest is None:
        return []
    if latest.get("final_gate_decision") != "GO FOR NEXT ISSUE":
        return [
            "session-start blocked because the latest closed pass-contract report did not end with GO FOR NEXT ISSUE"
        ]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify pass-contract wiring and runtime gate state.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--policy-only", action="store_true")
    group.add_argument("--active", action="store_true")
    group.add_argument("--pre-commit", action="store_true")
    group.add_argument("--pre-push", action="store_true")
    group.add_argument("--session-start", action="store_true")
    return parser


def _run_errors(errors: list[str], ok_message: str) -> int:
    if errors:
        raise SystemExit("pass contract verification failed:\n- " + "\n- ".join(errors))
    print(ok_message)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.policy_only:
        return _run_errors(collect_policy_errors(PROJECT_ROOT), "pass_contract_policy_ok")
    if args.active:
        return _run_errors(collect_active_report_errors(PROJECT_ROOT), "pass_contract_active_ok")
    if args.pre_commit:
        return _run_errors(collect_pre_commit_errors(PROJECT_ROOT), "pass_contract_pre_commit_ok")
    if args.pre_push:
        return _run_errors(collect_pre_push_errors(PROJECT_ROOT), "pass_contract_pre_push_ok")
    if args.session_start:
        return _run_errors(collect_session_start_errors(PROJECT_ROOT), "pass_contract_session_start_ok")
    parser.error("A verification mode is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
