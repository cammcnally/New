"""Run the full market-data pipeline: raw -> bronze -> silver -> gold -> QA."""
from __future__ import annotations

import json
from pathlib import Path

from market_data.common.build_contract import default_report_inventory
from market_data.common.io_parquet import row_count
from market_data.common.logging import get_logger
from market_data.common.manifest import (
    build_dataset_build_id,
    build_dataset_entry,
    build_manifest,
    write_manifest,
)
from market_data.common.paths import gold_path, manifest_dir, qa_dir, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("orchestration.all")

_MANIFEST_DATASETS = (
    ("instrument_master", "silver", ["bronze/av_listing_status"]),
    ("instrument_symbol_history", "silver", ["silver/instrument_master", "bronze/av_listing_status"]),
    ("benchmark_definitions", "silver", ["configs/benchmarks.yaml"]),
    ("security_master", "silver", ["silver/instrument_master"]),
    ("symbol_map_history", "silver", ["silver/instrument_symbol_history", "silver/security_master"]),
    ("prices_1d_unadjusted", "silver", ["bronze/yfinance_prices_1d", "bronze/stooq_prices_1d"]),
    ("macro_observations_vintage", "silver", ["bronze/fred_vintages", "bronze/fred_observations"]),
    ("macro_asof_daily", "silver", ["silver/macro_observations_vintage"]),
    ("trading_calendar", "silver", ["configs/benchmarks.yaml"]),
    ("gold_daily_panel", "gold", ["silver/prices_1d_split_adjusted", "silver/universe_membership"]),
)
_DEFERRED_COMPONENTS = [
    "instrument_classification_history",
    "instrument_benchmark_map",
]


def _dataset_path(name: str, layer: str, settings: IngestionSettings) -> Path:
    if layer == "silver":
        return silver_path(name, settings)
    if layer == "gold":
        return gold_path(name, settings)
    raise ValueError(f"Unsupported manifest layer: {layer}")


def _collect_manifest_datasets(settings: IngestionSettings) -> list[dict[str, object]]:
    datasets: list[dict[str, object]] = []
    for name, layer, source_inputs in _MANIFEST_DATASETS:
        path = _dataset_path(name, layer, settings)
        if not path.exists():
            continue
        count = row_count(path)
        if count <= 0:
            continue
        datasets.append(
            build_dataset_entry(
                name=name,
                layer=layer,
                source_inputs=list(source_inputs),
                data_path=path,
                row_count=count,
            )
        )
    return datasets


def _verification_artifacts(settings: IngestionSettings) -> list[dict[str, str]]:
    audit_path = qa_dir(settings) / "audit_findings.json"
    report_path = qa_dir(settings) / "report.html"
    artifacts: list[dict[str, str]] = []
    if audit_path.exists():
        artifacts.append({"name": "qa_audit_findings", "path": str(audit_path)})
    if report_path.exists():
        artifacts.append({"name": "qa_html_report", "path": str(report_path)})
    return artifacts


def _read_quarantined_row_count(settings: IngestionSettings) -> int:
    report_counts = []
    for path_name, summary_key in (
        ("unresolved_identity_prices_1d.json", "unresolved_rows"),
        ("invalid_ohlc_prices_1d.json", "invalid_ohlc_rows"),
    ):
        report_path = qa_dir(settings) / path_name
        if not report_path.exists():
            continue
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        summary = payload.get("summary") or {}
        raw_count = summary.get(summary_key, 0)
        try:
            report_counts.append(int(raw_count))
        except (TypeError, ValueError):
            report_counts.append(0)
    return sum(report_counts)


def _write_quarantine_report(settings: IngestionSettings) -> str:
    report_path = qa_dir(settings) / "quarantine_summary.json"
    quarantined_rows = _read_quarantined_row_count(settings)
    payload = {
        "summary": {
            "quarantined_rows": quarantined_rows,
            "has_unresolved_identity_report": (qa_dir(settings) / "unresolved_identity_prices_1d.json").exists(),
            "has_invalid_ohlc_report": (qa_dir(settings) / "invalid_ohlc_prices_1d.json").exists(),
        },
        "sources": {
            "unresolved_identity_prices_1d": str(qa_dir(settings) / "unresolved_identity_prices_1d.json")
            if (qa_dir(settings) / "unresolved_identity_prices_1d.json").exists()
            else None,
            "invalid_ohlc_prices_1d": str(qa_dir(settings) / "invalid_ohlc_prices_1d.json")
            if (qa_dir(settings) / "invalid_ohlc_prices_1d.json").exists()
            else None,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(report_path)


def _report_inventory(settings: IngestionSettings) -> dict[str, str | None]:
    reports = default_report_inventory()
    coverage_path = qa_dir(settings) / "source_coverage.json"
    unresolved_path = qa_dir(settings) / "unresolved_identity_prices_1d.json"
    quarantine_path = qa_dir(settings) / "quarantine_summary.json"
    final_summary_path = manifest_dir(settings) / "final_pass_fail_summary.json"

    if coverage_path.exists():
        reports["source_coverage_report"] = str(coverage_path)
    if unresolved_path.exists():
        reports["unresolved_identity_report"] = str(unresolved_path)
    if quarantine_path.exists():
        reports["quarantine_report"] = str(quarantine_path)
    if final_summary_path.exists():
        reports["final_pass_fail_summary"] = str(final_summary_path)
    return reports


def _table_has_rows(name: str, layer: str, settings: IngestionSettings) -> bool:
    path = _dataset_path(name, layer, settings)
    return path.exists() and row_count(path) > 0


def _compatibility_fallback_used(silver_results: dict[str, object]) -> bool:
    for result in silver_results.values():
        if isinstance(result, dict) and result.get("used_security_master_fallback") is True:
            return True
    return False


def _build_domain_statuses(
    *,
    settings: IngestionSettings,
    qa_results: dict[str, object],
    silver_results: dict[str, object],
    coverage_results: dict[str, object] | None,
    reports: dict[str, str | None],
) -> dict[str, object]:
    qa_error_count = 0
    qa_warning_count = 0
    for findings in qa_results.values():
        if isinstance(findings, dict):
            qa_error_count += len(findings.get("errors", []))
            qa_warning_count += len(findings.get("warnings", []))

    coverage_errors = coverage_results.get("errors", []) if isinstance(coverage_results, dict) else []
    coverage_warnings = coverage_results.get("warnings", []) if isinstance(coverage_results, dict) else []
    quarantined_rows = _read_quarantined_row_count(settings)
    compatibility_fallback_used = _compatibility_fallback_used(silver_results)

    required_core_blockers: list[str] = []
    if qa_error_count:
        required_core_blockers.append("qa_errors_present")
    if compatibility_fallback_used:
        required_core_blockers.append("compatibility_fallback_used")
    if coverage_errors:
        required_core_blockers.append("source_coverage_errors")
    for dataset_name in (
        "instrument_master",
        "instrument_symbol_history",
        "prices_1d_unadjusted",
        "benchmark_definitions",
        "trading_calendar",
    ):
        if not _table_has_rows(dataset_name, "silver", settings):
            required_core_blockers.append(f"missing_or_empty:{dataset_name}")
    for report_name in ("source_coverage_report", "unresolved_identity_report", "quarantine_report"):
        if not reports.get(report_name):
            required_core_blockers.append(f"missing_report:{report_name}")

    required_core_warnings: list[str] = []
    if qa_warning_count:
        required_core_warnings.append("qa_warnings_present")
    if quarantined_rows:
        required_core_warnings.append("quarantined_rows_present")
    if coverage_warnings:
        required_core_warnings.append("source_coverage_warnings")

    macro_present = _table_has_rows("macro_observations_vintage", "silver", settings) and _table_has_rows(
        "macro_asof_daily", "silver", settings
    )
    optional_enrichment_warnings: list[str] = []
    if not macro_present:
        optional_enrichment_warnings.append("macro_domain_deferred_or_missing")
    optional_enrichment_warnings.append("fundamentals_domain_deferred_or_partial")

    return {
        "required_core": {
            "status": "blocking_failure" if required_core_blockers else "ready_with_warnings" if required_core_warnings else "ready",
            "blocking_failures": required_core_blockers,
            "warnings": required_core_warnings,
            "quarantined_rows": quarantined_rows,
            "coverage_error_count": len(coverage_errors),
            "coverage_warning_count": len(coverage_warnings),
        },
        "optional_enrichment": {
            "status": "present_with_warnings" if macro_present else "deferred_or_partial",
            "warnings": optional_enrichment_warnings,
            "macro_present": macro_present,
        },
    }


def _write_final_pass_fail_summary(
    *,
    settings: IngestionSettings,
    dataset_build_id: str | None,
    qa_results: dict[str, object],
    silver_results: dict[str, object],
    coverage_results: dict[str, object] | None,
    reports: dict[str, str | None],
) -> Path:
    error_count = 0
    warning_count = 0
    for findings in qa_results.values():
        if isinstance(findings, dict):
            error_count += len(findings.get("errors", []))
            warning_count += len(findings.get("warnings", []))

    quarantined_rows = _read_quarantined_row_count(settings)
    compatibility_fallback_used = _compatibility_fallback_used(silver_results)
    domain_statuses = _build_domain_statuses(
        settings=settings,
        qa_results=qa_results,
        silver_results=silver_results,
        coverage_results=coverage_results,
        reports=reports,
    )
    required_core = domain_statuses["required_core"]
    required_core_blockers = list(required_core.get("blocking_failures", []))
    optional_enrichment = domain_statuses["optional_enrichment"]
    optional_enrichment_warnings = list(optional_enrichment.get("warnings", []))
    canonical_export_ready = error_count == 0 and not required_core_blockers
    final_status = (
        "failed"
        if not canonical_export_ready
        else "passed_with_warnings"
        if warning_count or quarantined_rows or optional_enrichment_warnings
        else "passed"
    )

    payload = {
        "dataset_build_id": dataset_build_id,
        "qa_error_count": error_count,
        "qa_warning_count": warning_count,
        "quarantined_rows": quarantined_rows,
        "compatibility_fallback_used": compatibility_fallback_used,
        "required_core_blocking_failures": required_core_blockers,
        "optional_enrichment_warnings": optional_enrichment_warnings,
        "domain_statuses": domain_statuses,
        "final_status": final_status,
        "canonical_export_ready": canonical_export_ready,
    }
    out = manifest_dir(settings) / "final_pass_fail_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def run_all(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
    fail_fast: bool = False,
) -> dict[str, object]:
    from market_data.orchestration.run_bronze import run_bronze
    from market_data.orchestration.run_gold import run_gold
    from market_data.orchestration.run_qa import run_qa
    from market_data.orchestration.run_raw import run_raw
    from market_data.orchestration.run_silver import run_silver

    results: dict[str, object] = {}

    log.info("=== PHASE 1: RAW ===")
    results["raw"] = run_raw(
        settings=settings,
        source="all",
        start_date=start_date,
        end_date=end_date,
        full_refresh=full_refresh,
        fail_fast=fail_fast,
    )

    log.info("=== PHASE 2: BRONZE ===")
    results["bronze"] = run_bronze(
        settings=settings,
        dataset="all",
        start_date=start_date,
        end_date=end_date,
        full_refresh=full_refresh,
        fail_fast=fail_fast,
    )

    log.info("=== PHASE 3: SILVER ===")
    results["silver"] = run_silver(
        settings=settings,
        dataset="all",
        start_date=start_date,
        end_date=end_date,
        full_refresh=full_refresh,
        fail_fast=fail_fast,
    )

    log.info("=== PHASE 4: GOLD ===")
    results["gold"] = run_gold(
        settings=settings,
        dataset="all",
        start_date=start_date,
        end_date=end_date,
        full_refresh=full_refresh,
        fail_fast=fail_fast,
    )

    log.info("=== PHASE 5: QA ===")
    results["qa"] = run_qa(settings=settings, fail_fast=fail_fast)

    log.info("=== COVERAGE AUDIT ===")
    try:
        from market_data.qa.qa_source_coverage import check as coverage_check

        results["coverage"] = coverage_check(settings=settings)
    except Exception:
        log.exception("coverage audit failed (non-fatal)")

    quarantine_report_path = _write_quarantine_report(settings)
    reports = _report_inventory(settings)

    log.info("=== WRITING MANIFEST ===")
    datasets = _collect_manifest_datasets(settings)
    silver_results = results.get("silver", {}) if isinstance(results.get("silver"), dict) else {}
    qa_results = results.get("qa", {}) if isinstance(results.get("qa"), dict) else {}
    coverage_results = results.get("coverage") if isinstance(results.get("coverage"), dict) else None
    domain_statuses = _build_domain_statuses(
        settings=settings,
        qa_results=qa_results,
        silver_results=silver_results,
        coverage_results=coverage_results,
        reports=reports,
    )
    compatibility_fallback_used = _compatibility_fallback_used(silver_results)
    manifest = build_manifest(
        datasets=datasets,
        dataset_build_id=build_dataset_build_id(datasets) if datasets else None,
        verification_artifacts=_verification_artifacts(settings),
        deferred_components=_DEFERRED_COMPONENTS,
        reports=reports,
        domain_statuses=domain_statuses,
        compatibility_fallback_used=compatibility_fallback_used,
    )
    out = manifest_dir(settings) / "dataset_manifest.json"
    write_manifest(manifest, out)
    summary_path = _write_final_pass_fail_summary(
        settings=settings,
        dataset_build_id=manifest.get("dataset_build_id"),
        qa_results=qa_results,
        silver_results=silver_results,
        coverage_results=coverage_results,
        reports=reports,
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest["reports"] = _report_inventory(settings)
    manifest["reports"]["canonical_build_manifest"] = str(out)
    manifest["reports"]["quarantine_report"] = quarantine_report_path
    manifest["reports"]["final_pass_fail_summary"] = str(summary_path)
    manifest["domain_statuses"] = summary["domain_statuses"]
    manifest["final_status"] = summary["final_status"]
    manifest["canonical_export_ready"] = summary["canonical_export_ready"]
    manifest["compatibility_fallback_used"] = summary["compatibility_fallback_used"]
    write_manifest(manifest, out)
    results["dataset_manifest_path"] = str(out)
    results["dataset_build_id"] = manifest.get("dataset_build_id")
    results["quarantine_report"] = quarantine_report_path
    results["final_pass_fail_summary"] = str(summary_path)
    log.info("manifest written to %s", out)

    log.info("=== COMPLETE ===")
    return results
