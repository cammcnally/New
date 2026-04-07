from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.repo_authority_common import classify_path, load_repo_authority_registry, normalize_path, path_matches

DEFAULT_POLICY_RELATIVE = "config/canonical/pass_contract_policy.json"


@dataclass(frozen=True)
class PassContractPaths:
    policy_path: Path
    template_path: Path
    runtime_root: Path
    report_root: Path
    active_issue_path: Path
    history_log_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{normalize_path(path)} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def normalize_paths(paths: Iterable[str]) -> list[str]:
    normalized = [normalize_path(path) for path in paths if str(path).strip()]
    return sorted(dict.fromkeys(normalized))


def load_pass_contract_policy(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    policy_path = project_root / DEFAULT_POLICY_RELATIVE
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{DEFAULT_POLICY_RELATIVE} must contain a JSON object")
    _validate_policy_payload(payload)
    return payload


def _validate_policy_payload(policy: dict[str, Any]) -> None:
    required_keys = (
        "schema_version",
        "canonical_spec_path",
        "report_template_path",
        "runtime_state_root",
        "report_root",
        "active_issue_path",
        "history_log_path",
        "issue_id_pattern",
        "required_fields",
        "required_scope_fields",
        "allowed_final_gate_decisions",
        "protected_surface_patterns",
        "blocking_criteria",
        "verification_rules",
    )
    missing = [key for key in required_keys if key not in policy]
    if missing:
        raise SystemExit(f"pass contract policy missing keys: {missing}")
    for key in ("required_fields", "required_scope_fields", "allowed_final_gate_decisions", "protected_surface_patterns"):
        _validate_string_list(policy[key], key)
    if not isinstance(policy["blocking_criteria"], dict):
        raise SystemExit("pass contract policy blocking_criteria must be an object")
    if not isinstance(policy["verification_rules"], list):
        raise SystemExit("pass contract policy verification_rules must be a list")


def _validate_string_list(value: object, label: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise SystemExit(f"pass contract policy {label} must be a non-empty list of strings")


def load_pass_contract_template(project_root: Path = PROJECT_ROOT, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active_policy = policy or load_pass_contract_policy(project_root)
    template_path = project_root / str(active_policy["report_template_path"])
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{active_policy['report_template_path']} must contain a JSON object")
    return payload


def get_pass_contract_paths(project_root: Path = PROJECT_ROOT, policy: dict[str, Any] | None = None) -> PassContractPaths:
    active_policy = policy or load_pass_contract_policy(project_root)
    return PassContractPaths(
        policy_path=project_root / DEFAULT_POLICY_RELATIVE,
        template_path=project_root / str(active_policy["report_template_path"]),
        runtime_root=project_root / str(active_policy["runtime_state_root"]),
        report_root=project_root / str(active_policy["report_root"]),
        active_issue_path=project_root / str(active_policy["active_issue_path"]),
        history_log_path=project_root / str(active_policy["history_log_path"]),
    )


def report_path_for_issue(issue_id: str, paths: PassContractPaths) -> Path:
    return paths.report_root / issue_id / "pass_report.json"


def run_git_lines(project_root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [normalize_path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def current_governed_changes(project_root: Path, registry: dict[str, Any]) -> list[str]:
    candidates: set[str] = set()
    for args in (
        ("diff", "--name-only"),
        ("diff", "--cached", "--name-only"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        candidates.update(run_git_lines(project_root, *args))
    return sorted(
        path for path in candidates if not path.startswith(".local/") and classify_path(path, registry)
    )


def staged_governed_changes(project_root: Path, registry: dict[str, Any]) -> list[str]:
    staged = run_git_lines(project_root, "diff", "--cached", "--name-only")
    return sorted(path for path in staged if not path.startswith(".local/") and classify_path(path, registry))


def sha256_path(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_path_state(project_root: Path, relative_path: str) -> dict[str, Any]:
    target = project_root / relative_path
    return {
        "exists": target.exists(),
        "sha256": sha256_path(target),
    }


def build_baseline_snapshot(project_root: Path, registry: dict[str, Any], planned_files: list[str]) -> dict[str, Any]:
    dirty_paths = current_governed_changes(project_root, registry)
    snapshot_paths = sorted(set(dirty_paths) | set(planned_files))
    file_states = {path: capture_path_state(project_root, path) for path in snapshot_paths}
    return {
        "captured_at": utc_now(),
        "dirty_paths": dirty_paths,
        "file_states": file_states,
    }


def compute_touched_paths_since_start(
    project_root: Path,
    baseline_snapshot: dict[str, Any],
    registry: dict[str, Any],
) -> list[str]:
    baseline_states = baseline_snapshot.get("file_states", {})
    if not isinstance(baseline_states, dict):
        raise SystemExit("baseline_snapshot.file_states must be an object")
    current_dirty = set(current_governed_changes(project_root, registry))
    candidate_paths = set(current_dirty) | {normalize_path(path) for path in baseline_states}
    touched: list[str] = []
    for relative_path in sorted(candidate_paths):
        baseline_state = baseline_states.get(relative_path)
        current_state = capture_path_state(project_root, relative_path)
        if baseline_state is None or baseline_state != current_state:
            touched.append(relative_path)
    return touched


def path_is_protected_or_frozen(relative_path: str, registry: dict[str, Any], policy: dict[str, Any]) -> bool:
    buckets = set(classify_path(relative_path, registry))
    if "protected_authorities" in buckets or "frozen_boundary_only" in buckets:
        return True
    return any(path_matches(relative_path, pattern) for pattern in policy["protected_surface_patterns"])


def protected_or_frozen_paths(
    relative_paths: Iterable[str], registry: dict[str, Any], policy: dict[str, Any]
) -> list[str]:
    return sorted(
        path for path in normalize_paths(relative_paths) if path_is_protected_or_frozen(path, registry, policy)
    )


def load_active_issue(paths: PassContractPaths) -> dict[str, Any] | None:
    if not paths.active_issue_path.exists():
        return None
    payload = json.loads(paths.active_issue_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("active pass contract state must be a JSON object")
    return payload


def write_active_issue(paths: PassContractPaths, payload: dict[str, Any]) -> None:
    write_json(paths.active_issue_path, payload)


def clear_active_issue(paths: PassContractPaths) -> None:
    if paths.active_issue_path.exists():
        paths.active_issue_path.unlink()


def latest_history_record(paths: PassContractPaths) -> dict[str, Any] | None:
    if not paths.history_log_path.exists():
        return None
    lines = [line for line in paths.history_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise SystemExit("pass contract history entries must be JSON objects")
    return payload


def append_history_record(paths: PassContractPaths, payload: dict[str, Any]) -> None:
    paths.history_log_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.history_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def seeded_report(
    project_root: Path,
    issue_id: str,
    objective: str,
    planned_files: list[str],
    acceptance_criteria: list[str],
    touches_protected_or_frozen: bool,
) -> dict[str, Any]:
    policy = load_pass_contract_policy(project_root)
    registry = load_repo_authority_registry(project_root / "config" / "canonical" / "repo_authority.yaml")
    template = copy.deepcopy(load_pass_contract_template(project_root, policy))
    planned = normalize_paths(planned_files)
    protected_paths = protected_or_frozen_paths(planned, registry, policy)
    if touches_protected_or_frozen != bool(protected_paths):
        raise SystemExit(
            "touches-protected-or-frozen must exactly match the planned protected/frozen file set"
        )
    template["schema_version"] = str(policy["schema_version"])
    template["report_status"] = "in_progress"
    template["created_at"] = utc_now()
    template["issue_id"] = issue_id
    template["objective"] = objective
    template["planned_files"] = planned
    template["protected_or_frozen_surface_touch"] = {
        "declared": touches_protected_or_frozen,
        "paths": protected_paths,
        "reason": (
            "Protected or frozen surfaces were declared in scope before editing."
            if touches_protected_or_frozen
            else "No protected or frozen surfaces were declared in scope before editing."
        ),
    }
    criteria = [item.strip() for item in acceptance_criteria if item.strip()]
    template["acceptance_criteria"] = criteria
    template["acceptance_criteria_results"] = [
        {
            "criterion": criterion,
            "satisfied": False,
            "evidence": "",
        }
        for criterion in criteria
    ]
    template["baseline_snapshot"] = build_baseline_snapshot(project_root, registry, planned)
    return template


def validate_issue_id(issue_id: str, policy: dict[str, Any]) -> list[str]:
    pattern = str(policy["issue_id_pattern"])
    if not re.fullmatch(pattern, issue_id):
        return [f"issue_id does not match required pattern: {pattern}"]
    return []


def _require_string(value: object, label: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"{label} must be a non-empty string"]
    return []


def _require_string_list(value: object, label: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"{label} must be a list of strings"]
    if not allow_empty and not any(item.strip() for item in value):
        return [f"{label} must not be empty"]
    if any(not item.strip() for item in value):
        return [f"{label} must not contain blank entries"]
    return []


def collect_scope_errors(report: dict[str, Any], policy: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in policy["required_scope_fields"]:
        if field not in report:
            errors.append(f"missing required scope field: {field}")
    errors.extend(validate_issue_id(str(report.get("issue_id", "")), policy))
    errors.extend(_require_string(report.get("objective"), "objective"))
    errors.extend(_require_string_list(report.get("planned_files"), "planned_files", allow_empty=False))
    errors.extend(_require_string_list(report.get("acceptance_criteria"), "acceptance_criteria", allow_empty=False))

    protected_decl = report.get("protected_or_frozen_surface_touch")
    if not isinstance(protected_decl, dict):
        errors.append("protected_or_frozen_surface_touch must be an object")
        return errors
    if not isinstance(protected_decl.get("declared"), bool):
        errors.append("protected_or_frozen_surface_touch.declared must be boolean")
    errors.extend(_require_string_list(protected_decl.get("paths"), "protected_or_frozen_surface_touch.paths", allow_empty=True))
    errors.extend(_require_string(protected_decl.get("reason"), "protected_or_frozen_surface_touch.reason"))

    planned_files = normalize_paths(report.get("planned_files", []))
    planned_protected = protected_or_frozen_paths(planned_files, registry, policy)
    declared_paths = normalize_paths(protected_decl.get("paths", []))
    declared = bool(protected_decl.get("declared"))
    if declared_paths != planned_protected:
        errors.append(
            f"protected_or_frozen_surface_touch.paths must equal planned protected/frozen paths: {planned_protected}"
        )
    if declared != bool(planned_protected):
        errors.append("protected_or_frozen_surface_touch.declared does not match the planned protected/frozen scope")
    return errors


def collect_final_report_errors(
    report: dict[str, Any],
    policy: dict[str, Any],
    registry: dict[str, Any],
    *,
    touched_paths: Iterable[str] | None = None,
    report_path: str | None = None,
) -> list[str]:
    errors = collect_scope_errors(report, policy, registry)

    for field in policy["required_fields"]:
        if field not in report:
            errors.append(f"missing required report field: {field}")

    errors.extend(
        _require_string_list(report.get("plain_english_diff_summary"), "plain_english_diff_summary", allow_empty=False)
    )
    errors.extend(_require_string_list(report.get("commands_run"), "commands_run", allow_empty=False))
    errors.extend(_require_string_list(report.get("artifacts_produced"), "artifacts_produced", allow_empty=False))
    errors.extend(_require_string_list(report.get("unresolved_items"), "unresolved_items", allow_empty=True))
    errors.extend(_require_string_list(report.get("not_touched"), "not_touched", allow_empty=True))
    errors.extend(_require_string_list(report.get("separate_approval_needed"), "separate_approval_needed", allow_empty=True))
    errors.extend(_require_string(report.get("final_gate_reason"), "final_gate_reason"))

    files_changed = normalize_paths(report.get("files_changed", []))
    if not isinstance(report.get("files_changed"), list):
        errors.append("files_changed must be a list of strings")
    if touched_paths is not None and files_changed != normalize_paths(touched_paths):
        errors.append(f"files_changed must match the detected touched paths: {normalize_paths(touched_paths)}")

    if report_path is not None and report_path not in report.get("artifacts_produced", []):
        errors.append(f"artifacts_produced must include {report_path}")

    command_results = report.get("command_results")
    if not isinstance(command_results, list):
        errors.append("command_results must be a list")
        command_results = []
    command_order: list[str] = []
    for index, entry in enumerate(command_results, start=1):
        if not isinstance(entry, dict):
            errors.append(f"command_results[{index}] must be an object")
            continue
        command_order.append(str(entry.get("command", "")))
        errors.extend(_require_string(entry.get("command"), f"command_results[{index}].command"))
        if not isinstance(entry.get("exit_code"), int):
            errors.append(f"command_results[{index}].exit_code must be an integer")
        if entry.get("result") not in {"pass", "fail"}:
            errors.append(f"command_results[{index}].result must be 'pass' or 'fail'")
        for field_name in ("stdout", "stderr"):
            value = entry.get(field_name)
            if not isinstance(value, str):
                errors.append(f"command_results[{index}].{field_name} must be a string")
    if command_order != report.get("commands_run", []):
        errors.append("command_results.command order must exactly match commands_run")

    criteria_results = report.get("acceptance_criteria_results")
    criteria = report.get("acceptance_criteria", [])
    if not isinstance(criteria_results, list):
        errors.append("acceptance_criteria_results must be a list")
        criteria_results = []
    criteria_seen: list[str] = []
    satisfied_map: dict[str, bool] = {}
    for index, entry in enumerate(criteria_results, start=1):
        if not isinstance(entry, dict):
            errors.append(f"acceptance_criteria_results[{index}] must be an object")
            continue
        criterion = entry.get("criterion")
        criteria_seen.append(str(criterion))
        errors.extend(_require_string(criterion, f"acceptance_criteria_results[{index}].criterion"))
        if not isinstance(entry.get("satisfied"), bool):
            errors.append(f"acceptance_criteria_results[{index}].satisfied must be boolean")
        errors.extend(_require_string(entry.get("evidence"), f"acceptance_criteria_results[{index}].evidence"))
        satisfied_map[str(criterion)] = bool(entry.get("satisfied"))
    if sorted(criteria_seen) != sorted(str(item) for item in criteria):
        errors.append("acceptance_criteria_results must cover every acceptance criterion exactly once")

    drift_check = report.get("protected_surface_drift_check")
    if not isinstance(drift_check, dict):
        errors.append("protected_surface_drift_check must be an object")
        drift_check = {}
    if not isinstance(drift_check.get("unexpected_drift"), bool):
        errors.append("protected_surface_drift_check.unexpected_drift must be boolean")
    errors.extend(_require_string_list(drift_check.get("paths"), "protected_surface_drift_check.paths", allow_empty=True))
    errors.extend(_require_string(drift_check.get("reason"), "protected_surface_drift_check.reason"))

    decision = report.get("final_gate_decision")
    if decision not in policy["allowed_final_gate_decisions"]:
        errors.append(f"final_gate_decision must be one of {policy['allowed_final_gate_decisions']}")

    planned_files = normalize_paths(report.get("planned_files", []))
    unexpected_scope = sorted(set(files_changed) - set(planned_files))
    if unexpected_scope:
        errors.append(f"files_changed contains undeclared scope paths: {unexpected_scope}")

    protected_touched = protected_or_frozen_paths(files_changed, registry, policy)
    declared_paths = normalize_paths(report.get("protected_or_frozen_surface_touch", {}).get("paths", []))
    unexpected_protected = sorted(set(protected_touched) - set(declared_paths))
    if unexpected_protected:
        errors.append(f"unexpected protected/frozen paths were touched: {unexpected_protected}")

    commands_run = [str(item) for item in report.get("commands_run", [])]
    rule_errors = collect_verification_rule_errors(
        commands_run=commands_run,
        changed_paths=files_changed,
        protected_paths=protected_touched,
        policy=policy,
    )
    errors.extend(rule_errors)

    if decision == "GO FOR NEXT ISSUE":
        unsatisfied = sorted(criterion for criterion in criteria if not satisfied_map.get(str(criterion), False))
        if unsatisfied:
            errors.append(f"GO FOR NEXT ISSUE requires every acceptance criterion to pass: {unsatisfied}")
        failed_commands = [entry["command"] for entry in command_results if isinstance(entry, dict) and entry.get("exit_code") != 0]
        if failed_commands:
            errors.append(f"GO FOR NEXT ISSUE requires all recorded commands to pass: {failed_commands}")
        if drift_check.get("unexpected_drift"):
            errors.append("GO FOR NEXT ISSUE is not allowed when protected_surface_drift_check.unexpected_drift is true")
        if report.get("unresolved_items"):
            errors.append("GO FOR NEXT ISSUE requires unresolved_items to be empty")
        if report.get("separate_approval_needed"):
            errors.append("GO FOR NEXT ISSUE requires separate_approval_needed to be empty")

    return sorted(dict.fromkeys(errors))


def collect_verification_rule_errors(
    *,
    commands_run: list[str],
    changed_paths: list[str],
    protected_paths: list[str],
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for rule in policy["verification_rules"]:
        if not isinstance(rule, dict):
            errors.append("verification_rules must contain only objects")
            continue
        name = str(rule.get("name", "unnamed_rule"))
        if not _verification_rule_applies(rule, changed_paths, protected_paths):
            continue
        snippets = rule.get("command_contains_any", [])
        if not isinstance(snippets, list) or not all(isinstance(item, str) and item.strip() for item in snippets):
            errors.append(f"verification rule {name} command_contains_any must be a list of strings")
            continue
        matched = any(snippet in command for command in commands_run for snippet in snippets)
        if not matched:
            errors.append(f"missing required verification command for rule {name}")
    return errors


def _verification_rule_applies(rule: dict[str, Any], changed_paths: list[str], protected_paths: list[str]) -> bool:
    when = str(rule.get("when", "always"))
    if when == "always":
        pass
    elif when == "protected_or_frozen_touched":
        if not protected_paths:
            return False
    else:
        raise SystemExit(f"Unsupported verification rule condition: {when}")

    patterns = rule.get("when_any_changed_matches")
    if patterns is None:
        return True
    if not isinstance(patterns, list) or not all(isinstance(item, str) and item.strip() for item in patterns):
        raise SystemExit("when_any_changed_matches must be a list of path patterns")
    return any(path_matches(path, pattern) for path in changed_paths for pattern in patterns)
