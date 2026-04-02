"""Core orchestrator for bootstrap and sync commands.

bootstrap: full historical backfill from start_date to today.
sync: incremental update from last watermark to today.

Both run the daily critical path:
  listing ingest -> bronze -> canonical identity -> compatibility identity ->
  prices -> calendar
"""
from __future__ import annotations

from market_data.common.dates import today_utc, parse_date
from market_data.common.logging import get_logger
from market_data.common.manifest import read_watermark, write_watermark
from market_data.common.settings import IngestionSettings
from market_data.orchestration.run_all import run_all

log = get_logger("orchestration.sync")


def _run_critical_path(
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool,
) -> dict[str, object]:
    """Execute the shared canonical build path."""
    return run_all(
        settings=settings,
        start_date=start_date,
        end_date=end_date,
        full_refresh=full_refresh,
        fail_fast=False,
    )


def run_bootstrap(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str | None = None,
) -> dict[str, object]:
    ed = end_date or today_utc().isoformat()
    log.info("BOOTSTRAP: %s -> %s", start_date, ed)

    results = _run_critical_path(settings, start_date, ed, full_refresh=True)

    log.info("=== COVERAGE AUDIT ===")
    try:
        from market_data.qa.qa_source_coverage import check as coverage_check
        results["coverage"] = coverage_check(settings=settings)
    except Exception:
        log.exception("coverage audit failed (non-fatal)")

    wp = write_watermark(settings, start_date=start_date, end_date=ed, phase="bootstrap")
    log.info("watermark written: %s", wp)
    log.info("BOOTSTRAP COMPLETE")
    return results


def run_sync(*, settings: IngestionSettings) -> dict[str, object]:
    wm = read_watermark(settings)
    if wm is None:
        raise RuntimeError(
            "No watermark found. Run 'python -m market_data.cli bootstrap --start-date YYYY-MM-DD' first."
        )

    prev_end = wm["end_date"]
    new_end = today_utc().isoformat()
    log.info("SYNC: %s -> %s (incremental from watermark)", prev_end, new_end)

    results = _run_critical_path(settings, prev_end, new_end, full_refresh=False)

    log.info("=== COVERAGE AUDIT ===")
    try:
        from market_data.qa.qa_source_coverage import check as coverage_check
        results["coverage"] = coverage_check(settings=settings)
    except Exception:
        log.exception("coverage audit failed (non-fatal)")

    wp = write_watermark(settings, start_date=wm["start_date"], end_date=new_end, phase="sync")
    log.info("watermark updated: %s", wp)
    log.info("SYNC COMPLETE")
    return results


def run_status(*, settings: IngestionSettings) -> dict[str, object]:
    """Report current data lake state."""
    from market_data.common.paths import silver_path, lake_root
    from market_data.common.io_parquet import row_count
    import json

    status: dict[str, object] = {}

    wm = read_watermark(settings)
    if wm:
        status["watermark"] = wm
    else:
        status["watermark"] = "no watermark -- run bootstrap first"

    tables = [
        "instrument_master",
        "instrument_symbol_history",
        "security_master",
        "prices_1d_unadjusted",
        "trading_calendar",
    ]
    table_stats: dict[str, int] = {}
    for t in tables:
        p = silver_path(t, settings)
        table_stats[t] = row_count(p) if p.exists() else 0
    status["silver_row_counts"] = table_stats

    coverage_path = lake_root(settings) / "qa" / "source_coverage.json"
    if coverage_path.exists():
        try:
            coverage = json.loads(coverage_path.read_text())
            status["coverage_summary"] = {
                "listed": coverage.get("stats", {}).get("total_listed", 0),
                "priced": coverage.get("stats", {}).get("total_priced", 0),
                "matched": coverage.get("stats", {}).get("matched", 0),
                "listed_no_prices": len(coverage.get("listed_no_prices", [])),
                "priced_no_listing": len(coverage.get("priced_no_listing", [])),
            }
        except Exception:
            status["coverage_summary"] = "error reading coverage file"
    else:
        status["coverage_summary"] = "no coverage audit yet"

    return status
