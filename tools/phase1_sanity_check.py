#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


ASSESSMENT_STATUSES = ("ACTIVE", "SUPERSEDED", "ARCHIVED")
ASSESSMENT_AUTHORITY_LEVELS = ("advisory", "authoritative")
REQUIRED_ASSESSMENT_FIELDS = (
    "assessment_type",
    "status",
    "assessed_at",
    "assessed_from_commit",
    "authority_level",
    "canonical_path",
)


def _find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if candidate.is_file():
            candidate = candidate.parent
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Could not locate repo root via pyproject.toml")


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object at {path}")
    return payload


def _parse_version_text(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3:
        raise ValueError(f"Unsupported version text: {value}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def load_phase1_contract(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or DEFAULT_PROJECT_ROOT
    return _read_json_file(root / "control_plane" / "phase1_contract.json")


def load_assessment_registry(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or DEFAULT_PROJECT_ROOT
    return _read_json_file(root / "control_plane" / "assessment_registry.json")


DEFAULT_PROJECT_ROOT = _find_repo_root(Path(__file__))
PHASE1_CONTRACT = load_phase1_contract(DEFAULT_PROJECT_ROOT)
ASSESSMENT_REGISTRY = load_assessment_registry(DEFAULT_PROJECT_ROOT)

SUPPORTED_PYTHON_MIN = _parse_version_text(str(PHASE1_CONTRACT["python"]["min"]))
SUPPORTED_PYTHON_MAX_EXCLUSIVE = _parse_version_text(str(PHASE1_CONTRACT["python"]["max_exclusive"]))
ARTIFACT_SPECS: dict[str, dict[str, Any]] = {
    name: dict(spec) for name, spec in PHASE1_CONTRACT["artifacts"].items()
}
REQUIRED_REPORT_SECTIONS = tuple(PHASE1_CONTRACT["report_sections"])
REQUIRED_OVERALL_KEYS = tuple(ARTIFACT_SPECS["overall_metrics"]["required_keys"])
REQUIRED_FOLD_COLUMNS = tuple(ARTIFACT_SPECS["fold_metrics"]["required_columns"])
REQUIRED_THRESHOLD_COLUMNS = tuple(ARTIFACT_SPECS["threshold_candidate_diagnostics"]["required_columns"])
REQUIRED_POLICY_DAILY_COLUMNS = tuple(ARTIFACT_SPECS["policy_daily_returns"]["required_columns"])
REQUIRED_STRATEGY_KEYS = tuple(ARTIFACT_SPECS["best_strategy_summary"]["required_keys"])
REQUIRED_FEATURE_VALIDATION_COLUMNS = tuple(ARTIFACT_SPECS["feature_validation_report"]["required_columns"])
REQUIRED_MODEL_COMPARISON_COLUMNS = tuple(ARTIFACT_SPECS["model_comparison_report"]["required_columns"])
REQUIRED_POSITION_RANKING_COLUMNS = tuple(ARTIFACT_SPECS["position_ranking_audit"]["required_columns"])
REQUIRED_SCORECARD_COLUMNS = tuple(ARTIFACT_SPECS["strategy_scorecards"]["required_columns"])
REQUIRED_RESUME_KEYS = tuple(ARTIFACT_SPECS["resume_state"]["required_keys"])


def _require_supported_python_version(
    version_info: tuple[int, int, int] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> None:
    active_contract = contract or PHASE1_CONTRACT
    python_contract = active_contract["python"]
    min_version = _parse_version_text(str(python_contract["min"]))
    max_exclusive = _parse_version_text(str(python_contract["max_exclusive"]))
    current = tuple(version_info or tuple(sys.version_info[:3]))
    if current < min_version or current >= max_exclusive:
        current_text = ".".join(str(part) for part in current)
        min_text = ".".join(str(part) for part in min_version)
        max_text = ".".join(str(part) for part in max_exclusive)
        raise SystemExit(
            "Unsupported Python interpreter for this repository: "
            f"{current_text}. Use >={min_text},<{max_text} from the workspace virtual environment."
        )


_require_supported_python_version()


def _resolve_output_dir(output_dir: str, *, project_root: Path | None = None) -> Path:
    candidate = Path(output_dir)
    if candidate.is_absolute():
        return candidate
    root = project_root or DEFAULT_PROJECT_ROOT
    base = Path(os.environ.get("PIPELINE_BASE_PATH", str(root)))
    return (base / candidate).resolve()


def _missing_keys(mapping: Mapping[str, Any], required: Iterable[str]) -> list[str]:
    return [key for key in required if key not in mapping]


def _safe_read_text(path: Path, label: str) -> tuple[str | None, list[str]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except UnicodeDecodeError as exc:
        return None, [f"{label} could not be read as UTF-8: {exc}"]
    except OSError as exc:
        return None, [f"{label} could not be read: {exc}"]


def _safe_read_json(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    text, errors = _safe_read_text(path, label)
    if text is None:
        return None, errors
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"{label} is not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, [f"{label} is not a JSON object"]
    return payload, []


def _safe_read_csv_header(path: Path, label: str) -> tuple[list[str] | None, list[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                return None, [f"{label} is empty or missing a header row"]
            if not header:
                return None, [f"{label} is empty or missing a header row"]
            return header, []
    except UnicodeDecodeError as exc:
        return None, [f"{label} could not be read as UTF-8: {exc}"]
    except csv.Error as exc:
        return None, [f"{label} is not a valid CSV file: {exc}"]
    except OSError as exc:
        return None, [f"{label} could not be read: {exc}"]


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _artifact_paths(output_dir: Path, contract: Mapping[str, Any]) -> dict[str, Path]:
    return {
        name: output_dir / str(spec["relative_path"])
        for name, spec in contract["artifacts"].items()
    }


def _validate_required_values(
    payload: Mapping[str, Any],
    required_values: Mapping[str, Any],
    *,
    label: str,
) -> list[str]:
    errors: list[str] = []
    for key, expected_value in required_values.items():
        observed = payload.get(key)
        if isinstance(expected_value, bool):
            if _is_true(observed) is not expected_value:
                errors.append(f"{label} has {key} != {str(expected_value).lower()}")
            continue
        if observed != expected_value:
            errors.append(f"{label} has {key} != {expected_value}")
    return errors


def _validate_markdown_sections(
    path: Path,
    spec: Mapping[str, Any],
) -> list[str]:
    label = path.name
    text, errors = _safe_read_text(path, label)
    if text is None:
        return errors
    for section in spec.get("required_sections", ()):
        if section not in text:
            errors.append(f"{label} missing required section marker: {section}")
    return errors


def _validate_csv_artifact(path: Path, spec: Mapping[str, Any]) -> list[str]:
    label = path.name
    header, errors = _safe_read_csv_header(path, label)
    if header is None:
        return errors
    missing_columns = [column for column in spec.get("required_columns", ()) if column not in header]
    if missing_columns:
        errors.append(f"{label} missing columns: {', '.join(missing_columns)}")
    return errors


def _validate_json_artifact(path: Path, spec: Mapping[str, Any]) -> list[str]:
    label = path.name
    payload, errors = _safe_read_json(path, label)
    if payload is None:
        return errors
    missing_keys = _missing_keys(payload, spec.get("required_keys", ()))
    if missing_keys:
        errors.append(f"{label} missing keys: {', '.join(missing_keys)}")
    errors.extend(_validate_required_values(payload, spec.get("required_values", {}), label=label))
    return errors


def _validate_assessment_registry(
    project_root: Path,
    assessment_registry: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    records = assessment_registry.get("records")
    if not isinstance(records, list):
        return ["assessment_registry.json missing records list"]

    active_counts: dict[str, int] = {}
    seen_types: set[str] = set()
    for index, record in enumerate(records):
        label = f"assessment_registry.json record[{index}]"
        if not isinstance(record, Mapping):
            errors.append(f"{label} is not an object")
            continue
        missing_fields = _missing_keys(record, REQUIRED_ASSESSMENT_FIELDS)
        if missing_fields:
            errors.append(f"{label} missing fields: {', '.join(missing_fields)}")
            continue

        assessment_type = str(record["assessment_type"]).strip()
        status = str(record["status"]).strip()
        authority_level = str(record["authority_level"]).strip()
        canonical_path = project_root / str(record["canonical_path"])

        if not assessment_type:
            errors.append(f"{label} has empty assessment_type")
            continue
        seen_types.add(assessment_type)

        if status not in ASSESSMENT_STATUSES:
            errors.append(f"{label} has unsupported status: {status}")
        if authority_level not in ASSESSMENT_AUTHORITY_LEVELS:
            errors.append(f"{label} has unsupported authority_level: {authority_level}")
        if status == "ACTIVE":
            active_counts[assessment_type] = active_counts.get(assessment_type, 0) + 1
        if not canonical_path.exists():
            errors.append(f"{label} canonical path does not exist: {record['canonical_path']}")

    for assessment_type in sorted(seen_types):
        active_count = active_counts.get(assessment_type, 0)
        if active_count != 1:
            errors.append(
                f"assessment_registry.json has {active_count} ACTIVE records for assessment type {assessment_type}"
            )
    return errors


def _validate_legacy_surfaces(output_dir: Path, contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    legacy_surfaces = contract["legacy_surfaces"]
    legacy_resume = output_dir / str(legacy_surfaces["resume_state"])
    legacy_log = output_dir / str(legacy_surfaces["pipeline_log"])
    if legacy_resume.exists():
        errors.append(f"Legacy resume surface reintroduced at {legacy_resume}")
    if legacy_log.exists():
        errors.append(f"Legacy root log surface reintroduced at {legacy_log}")
    return errors


def validate(
    output_dir: Path,
    *,
    project_root: Path | None = None,
    contract: Mapping[str, Any] | None = None,
    assessment_registry: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    root = project_root or DEFAULT_PROJECT_ROOT
    active_contract = contract or PHASE1_CONTRACT
    active_registry = assessment_registry or ASSESSMENT_REGISTRY

    required_files = _artifact_paths(output_dir, active_contract)
    for label, path in required_files.items():
        if not path.exists():
            errors.append(f"Missing required artifact: {label} at {path}")

    errors.extend(_validate_legacy_surfaces(output_dir, active_contract))
    errors.extend(_validate_assessment_registry(root, active_registry))

    for label, path in required_files.items():
        if not path.exists():
            continue
        spec = active_contract["artifacts"][label]
        artifact_type = spec.get("type")
        if artifact_type == "json":
            errors.extend(_validate_json_artifact(path, spec))
        elif artifact_type == "csv":
            errors.extend(_validate_csv_artifact(path, spec))
        elif artifact_type == "markdown":
            errors.extend(_validate_markdown_sections(path, spec))
        else:
            errors.append(f"Unsupported artifact contract type for {label}: {artifact_type}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 1 pipeline artifacts and guardrail fields.")
    parser.add_argument("--output_dir", required=True, help="Relative or absolute pipeline output directory")
    args = parser.parse_args(argv)
    output_dir = _resolve_output_dir(args.output_dir, project_root=DEFAULT_PROJECT_ROOT)
    errors = validate(output_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Phase 1 sanity check passed for {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
