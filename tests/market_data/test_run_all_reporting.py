from __future__ import annotations

import json

import pytest

from market_data.common.paths import qa_dir
from market_data.orchestration import run_all as run_all_module

pytestmark = pytest.mark.ingestion


def test_report_inventory_tracks_known_report_paths(test_settings) -> None:
    qa_root = qa_dir(test_settings)
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "source_coverage.json").write_text("{}", encoding="utf-8")
    (qa_root / "unresolved_identity_prices_1d.json").write_text(
        json.dumps({"summary": {"unresolved_rows": 2}}),
        encoding="utf-8",
    )

    quarantine_path = run_all_module._write_quarantine_report(test_settings)
    reports = run_all_module._report_inventory(test_settings)

    assert reports["source_coverage_report"] == str(qa_root / "source_coverage.json")
    assert reports["unresolved_identity_report"] == str(qa_root / "unresolved_identity_prices_1d.json")
    assert reports["quarantine_report"] == quarantine_path
    assert reports["export_panel_manifest"] is None


def test_final_pass_fail_summary_warns_for_quarantined_rows(test_settings) -> None:
    qa_root = qa_dir(test_settings)
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "unresolved_identity_prices_1d.json").write_text(
        json.dumps({"summary": {"unresolved_rows": 3}}),
        encoding="utf-8",
    )

    summary_path = run_all_module._write_final_pass_fail_summary(
        settings=test_settings,
        dataset_build_id="dataset-build-123",
        qa_results={"qa_prices": {"errors": [], "warnings": [], "stats": {}}},
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["dataset_build_id"] == "dataset-build-123"
    assert summary["final_status"] == "passed_with_warnings"
    assert summary["canonical_export_ready"] is True
    assert summary["quarantined_rows"] == 3
    assert summary["qa_error_count"] == 0


def test_final_pass_fail_summary_fails_when_qa_errors_exist(test_settings) -> None:
    summary_path = run_all_module._write_final_pass_fail_summary(
        settings=test_settings,
        dataset_build_id="dataset-build-123",
        qa_results={"qa_prices": {"errors": ["bad"], "warnings": [], "stats": {}}},
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["final_status"] == "failed"
    assert summary["canonical_export_ready"] is False
    assert summary["qa_error_count"] == 1
