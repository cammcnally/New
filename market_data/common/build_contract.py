from __future__ import annotations


ROW_STATES = (
    "RAW_ACCEPTED",
    "SILVER_RESOLVED",
    "SILVER_QUARANTINED",
    "EXPORT_ELIGIBLE",
    "EXPORT_EXCLUDED",
)

REQUIRED_REPORT_ARTIFACTS = (
    "canonical_build_manifest",
    "source_coverage_report",
    "unresolved_identity_report",
    "quarantine_report",
    "export_panel_manifest",
    "final_pass_fail_summary",
)


def default_report_inventory() -> dict[str, str | None]:
    return {name: None for name in REQUIRED_REPORT_ARTIFACTS}
