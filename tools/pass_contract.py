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
    append_history_record,
    clear_active_issue,
    collect_final_report_errors,
    collect_scope_errors,
    compute_touched_paths_since_start,
    get_pass_contract_paths,
    latest_history_record,
    load_active_issue,
    load_json,
    load_pass_contract_policy,
    normalize_paths,
    protected_or_frozen_paths,
    report_path_for_issue,
    seeded_report,
    utc_now,
    write_active_issue,
    write_json,
)
from tools.repo_authority_common import load_repo_authority_registry, normalize_path


def start_pass(
    project_root: Path,
    *,
    issue_id: str,
    objective: str,
    planned_files: list[str],
    acceptance_criteria: list[str],
    touches_protected_or_frozen: bool,
) -> dict[str, Any]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    paths = get_pass_contract_paths(project_root, policy)

    active_issue = load_active_issue(paths)
    if active_issue is not None:
        raise SystemExit(
            "pass contract start blocked: an active issue already exists at "
            f"{normalize_path(active_issue.get('report_path', paths.active_issue_path))}"
        )

    latest = latest_history_record(paths)
    if latest is not None and latest.get("final_gate_decision") != "GO FOR NEXT ISSUE":
        raise SystemExit(
            "pass contract start blocked by latest closed issue "
            f"{latest.get('issue_id')} with decision {latest.get('final_gate_decision')}"
        )

    report = seeded_report(
        project_root,
        issue_id=issue_id,
        objective=objective,
        planned_files=planned_files,
        acceptance_criteria=acceptance_criteria,
        touches_protected_or_frozen=touches_protected_or_frozen,
    )
    scope_errors = collect_scope_errors(report, policy, registry)
    if scope_errors:
        raise SystemExit("pass contract start failed:\n- " + "\n- ".join(scope_errors))

    report_path = report_path_for_issue(issue_id, paths)
    report_relative = normalize_path(report_path.relative_to(project_root))
    report["artifacts_produced"] = [report_relative]
    write_json(report_path, report)
    write_active_issue(
        paths,
        {
            "issue_id": issue_id,
            "report_path": report_relative,
            "started_at": utc_now(),
        },
    )

    payload = {
        "status": "started",
        "issue_id": issue_id,
        "report_path": report_relative,
        "planned_files": normalize_paths(planned_files),
    }
    print(json.dumps(payload, indent=2))
    return payload


def close_pass(project_root: Path, *, issue_id: str) -> dict[str, Any]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    paths = get_pass_contract_paths(project_root, policy)

    active_issue = load_active_issue(paths)
    if active_issue is None:
        raise SystemExit("pass contract close failed: no active issue is open")
    if active_issue.get("issue_id") != issue_id:
        raise SystemExit(
            "pass contract close failed: active issue "
            f"{active_issue.get('issue_id')} does not match requested issue {issue_id}"
        )

    report_path = project_root / str(active_issue["report_path"])
    report = load_json(report_path)
    touched_paths = compute_touched_paths_since_start(project_root, report.get("baseline_snapshot", {}), registry)
    report["files_changed"] = touched_paths

    report_relative = normalize_path(report_path.relative_to(project_root))
    artifacts = normalize_paths(report.get("artifacts_produced", []))
    if report_relative not in artifacts:
        artifacts.append(report_relative)
    report["artifacts_produced"] = normalize_paths(artifacts)

    protected_touched = protected_or_frozen_paths(touched_paths, registry, policy)
    declared_paths = normalize_paths(report.get("protected_or_frozen_surface_touch", {}).get("paths", []))
    unexpected_protected = sorted(set(protected_touched) - set(declared_paths))
    report["protected_surface_drift_check"] = {
        "unexpected_drift": bool(unexpected_protected),
        "paths": unexpected_protected,
        "reason": (
            "Unexpected protected or frozen paths were touched during the pass."
            if unexpected_protected
            else "No unexpected protected or frozen drift detected."
        ),
    }
    report["report_status"] = "closed"
    report["closed_at"] = utc_now()

    errors = collect_final_report_errors(
        report,
        policy,
        registry,
        touched_paths=touched_paths,
        report_path=report_relative,
    )
    if errors:
        raise SystemExit("pass contract close failed:\n- " + "\n- ".join(errors))

    write_json(report_path, report)
    append_history_record(
        paths,
        {
            "issue_id": issue_id,
            "report_path": report_relative,
            "closed_at": report["closed_at"],
            "final_gate_decision": report["final_gate_decision"],
            "final_gate_reason": report["final_gate_reason"],
            "files_changed": report["files_changed"],
            "protected_surface_drift_check": report["protected_surface_drift_check"],
        },
    )
    clear_active_issue(paths)

    payload = {
        "status": "closed",
        "issue_id": issue_id,
        "report_path": report_relative,
        "final_gate_decision": report["final_gate_decision"],
    }
    print(json.dumps(payload, indent=2))
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and close issue pass-contract packets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Create a new issue pass packet before editing")
    start_parser.add_argument("--issue-id", required=True)
    start_parser.add_argument("--objective", required=True)
    start_parser.add_argument("--planned-file", action="append", default=[], required=True)
    start_parser.add_argument("--acceptance", action="append", default=[], required=True)
    start_parser.add_argument("--touches-protected-or-frozen", choices=("yes", "no"), required=True)

    close_parser = subparsers.add_parser("close", help="Validate and close the active issue pass packet")
    close_parser.add_argument("--issue-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        start_pass(
            PROJECT_ROOT,
            issue_id=args.issue_id,
            objective=args.objective,
            planned_files=args.planned_file,
            acceptance_criteria=args.acceptance,
            touches_protected_or_frozen=args.touches_protected_or_frozen == "yes",
        )
        return 0
    if args.command == "close":
        close_pass(PROJECT_ROOT, issue_id=args.issue_id)
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
