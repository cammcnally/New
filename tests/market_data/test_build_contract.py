from __future__ import annotations

import pytest

from market_data.common.manifest import build_manifest

pytestmark = pytest.mark.ingestion


def test_build_contract_exposes_repo_wide_row_states() -> None:
    from market_data.common.build_contract import ROW_STATES, default_report_inventory

    assert ROW_STATES == (
        "RAW_ACCEPTED",
        "SILVER_RESOLVED",
        "SILVER_QUARANTINED",
        "EXPORT_ELIGIBLE",
        "EXPORT_EXCLUDED",
    )
    assert default_report_inventory() == {
        "canonical_build_manifest": None,
        "source_coverage_report": None,
        "unresolved_identity_report": None,
        "quarantine_report": None,
        "export_panel_manifest": None,
        "final_pass_fail_summary": None,
    }


def test_build_manifest_includes_repo_wide_reporting_block() -> None:
    from market_data.common.build_contract import ROW_STATES, default_report_inventory

    manifest = build_manifest(datasets=[], run_id="run-reporting-test")

    assert manifest["row_state_model"] == list(ROW_STATES)
    assert manifest["reports"] == default_report_inventory()
    assert manifest["domain_statuses"] == {}
    assert manifest["final_status"] == "unknown"
    assert manifest["canonical_export_ready"] is False
    assert manifest["compatibility_fallback_used"] is False
