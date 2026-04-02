"""Orchestrate QA checks and report generation."""
from __future__ import annotations

from market_data.common.logging import get_logger
from market_data.common.settings import IngestionSettings

log = get_logger("orchestration.qa")

QA_MODULES = [
    "market_data.qa.qa_security_master",
    "market_data.qa.qa_prices",
    "market_data.qa.qa_corporate_actions",
    "market_data.qa.qa_fundamentals",
    "market_data.qa.qa_macro",
    "market_data.qa.qa_universe",
    "market_data.qa.qa_storage",
]


def run_qa(
    *,
    settings: IngestionSettings,
    fail_fast: bool = False,
) -> dict[str, object]:
    import importlib

    all_findings: dict[str, object] = {}

    for mod_path in QA_MODULES:
        name = mod_path.rsplit(".", 1)[-1]
        log.info("running QA: %s", name)
        try:
            mod = importlib.import_module(mod_path)
            findings = mod.check(settings=settings)
            all_findings[name] = findings
            log.info("completed QA: %s — %s", name, "PASS" if not findings.get("errors") else "FAIL")
        except Exception:
            log.exception("failed QA: %s", name)
            if fail_fast:
                raise

    from market_data.qa.build_audit_report import build_report
    build_report(settings=settings, findings=all_findings)

    return all_findings
