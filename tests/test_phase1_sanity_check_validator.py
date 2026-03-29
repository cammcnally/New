from __future__ import annotations

import json
from pathlib import Path

import pytest

from Pipeline import POSITION_RANKING_AUDIT_COLUMNS
from tools.phase1_sanity_check import (
    REQUIRED_POSITION_RANKING_COLUMNS,
    _find_repo_root,
    load_phase1_contract,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]


def _base_contract(artifacts: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "test",
        "python": {"min": "3.11.9", "max_exclusive": "3.12.0"},
        "invariants": {},
        "legacy_surfaces": {
            "resume_state": "resume_state.json",
            "pipeline_log": "pipeline.log",
        },
        "report_sections": [],
        "artifacts": artifacts,
    }


def _write_assessment_doc(project_root: Path, relative_path: str) -> None:
    path = project_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Assessment\n", encoding="utf-8")


def _registry(
    project_root: Path,
    *,
    duplicate_active: bool = False,
    include_superseded: bool = False,
    missing_path: bool = False,
) -> dict[str, object]:
    active_path = "docs/assessments/test-latest.md"
    if not missing_path:
        _write_assessment_doc(project_root, active_path)
    records: list[dict[str, str]] = [
        {
            "assessment_type": "test_assessment",
            "status": "ACTIVE",
            "assessed_at": "2026-03-22 20:11 AEDT",
            "assessed_from_commit": "abc123",
            "authority_level": "advisory",
            "canonical_path": active_path,
        }
    ]
    if duplicate_active:
        records.append(
            {
                "assessment_type": "test_assessment",
                "status": "ACTIVE",
                "assessed_at": "2026-03-22 20:11 AEDT",
                "assessed_from_commit": "def456",
                "authority_level": "advisory",
                "canonical_path": active_path if not missing_path else "docs/assessments/missing.md",
            }
        )
    if include_superseded:
        archive_path = "docs/archive/assessments/test/2026-03-10_0000_aedt.md"
        _write_assessment_doc(project_root, archive_path)
        records.append(
            {
                "assessment_type": "test_assessment",
                "status": "SUPERSEDED",
                "assessed_at": "2026-03-10 00:00 AEDT",
                "assessed_from_commit": "old123",
                "authority_level": "advisory",
                "canonical_path": archive_path,
            }
        )
    return {"schema_version": "test", "records": records}


def test_validate_reports_missing_artifacts_and_registry_errors_together(tmp_path: Path) -> None:
    contract = _base_contract(
        {
            "overall_metrics": {
                "relative_path": "02_metrics/overall_metrics.json",
                "type": "json",
                "required_keys": ["trial_count_formal"],
                "required_values": {"trial_count_formal": 108},
            }
        }
    )
    registry = _registry(tmp_path, duplicate_active=True, missing_path=True)

    errors = validate(tmp_path, project_root=tmp_path, contract=contract, assessment_registry=registry)

    assert any("Missing required artifact: overall_metrics" in error for error in errors)
    assert any("ACTIVE records for assessment type test_assessment" in error for error in errors)
    assert any("canonical path does not exist" in error for error in errors)


def test_validate_returns_clean_error_for_malformed_json(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    path = output_dir / "02_metrics" / "overall_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    contract = _base_contract(
        {
            "overall_metrics": {
                "relative_path": "02_metrics/overall_metrics.json",
                "type": "json",
                "required_keys": ["trial_count_formal"],
                "required_values": {"trial_count_formal": 108},
            }
        }
    )
    registry = _registry(tmp_path)

    errors = validate(output_dir, project_root=tmp_path, contract=contract, assessment_registry=registry)

    assert any("overall_metrics.json is not valid JSON" in error for error in errors)


def test_validate_returns_clean_error_for_bad_csv_header(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    path = output_dir / "04_strategies" / "position_ranking_audit.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")

    contract = _base_contract(
        {
            "position_ranking_audit": {
                "relative_path": "04_strategies/position_ranking_audit.csv",
                "type": "csv",
                "required_columns": ["fold", "ticker"],
            }
        }
    )
    registry = _registry(tmp_path)

    errors = validate(output_dir, project_root=tmp_path, contract=contract, assessment_registry=registry)

    assert any("position_ranking_audit.csv is empty or missing a header row" in error for error in errors)


def test_find_repo_root_does_not_depend_on_current_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    assert _find_repo_root(Path(__file__)) == ROOT


def test_validate_uses_injected_contract_values_not_hardcoded_defaults(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    path = output_dir / "02_metrics" / "overall_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"trial_count_formal": 99}), encoding="utf-8")

    contract = _base_contract(
        {
            "overall_metrics": {
                "relative_path": "02_metrics/overall_metrics.json",
                "type": "json",
                "required_keys": ["trial_count_formal"],
                "required_values": {"trial_count_formal": 99},
            }
        }
    )
    registry = _registry(tmp_path)

    assert validate(output_dir, project_root=tmp_path, contract=contract, assessment_registry=registry) == []


def test_validate_accepts_superseded_assessment_records_without_treating_them_as_active(tmp_path: Path) -> None:
    contract = _base_contract({})
    registry = _registry(tmp_path, include_superseded=True)

    assert validate(tmp_path / "outputs", project_root=tmp_path, contract=contract, assessment_registry=registry) == []


def test_validate_still_catches_legacy_root_surfaces(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pipeline.log").write_text("legacy", encoding="utf-8")
    (output_dir / "resume_state.json").write_text("{}", encoding="utf-8")

    contract = _base_contract({})
    registry = _registry(tmp_path)

    errors = validate(output_dir, project_root=tmp_path, contract=contract, assessment_registry=registry)

    assert any("Legacy root log surface reintroduced" in error for error in errors)
    assert any("Legacy resume surface reintroduced" in error for error in errors)


def test_position_ranking_contract_matches_pipeline_writer_schema() -> None:
    contract = load_phase1_contract(ROOT)
    required_columns = tuple(contract["artifacts"]["position_ranking_audit"]["required_columns"])

    assert required_columns[: len(POSITION_RANKING_AUDIT_COLUMNS)] == POSITION_RANKING_AUDIT_COLUMNS
    assert required_columns == REQUIRED_POSITION_RANKING_COLUMNS
