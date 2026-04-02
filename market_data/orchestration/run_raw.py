"""Orchestrate raw-layer ingestion."""
from __future__ import annotations

from market_data.common.source_catalog import enabled_raw_sources
from market_data.common.logging import get_logger
from market_data.common.settings import IngestionSettings

log = get_logger("orchestration.raw")


def available_sources(settings: IngestionSettings) -> tuple[str, ...]:
    return enabled_raw_sources(settings)


def run_raw(
    *,
    settings: IngestionSettings,
    source: str = "all",
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
    symbols_file: str | None = None,
    fail_fast: bool = False,
) -> dict[str, object]:
    sources = available_sources(settings) if source == "all" else (source,)
    results: dict[str, object] = {}

    for src in sources:
        log.info("ingesting raw: %s", src)
        try:
            if src == "yfinance":
                from market_data.raw.ingest_yfinance_daily import ingest as ingest_daily

                results["yfinance_daily"] = ingest_daily(
                    settings=settings,
                    start_date=start_date,
                    end_date=end_date,
                    full_refresh=full_refresh,
                )
            elif src == "stooq":
                from market_data.raw.ingest_stooq_daily import ingest as ingest_daily
                from market_data.raw.ingest_stooq_intraday import ingest as ingest_intraday
                results["stooq_daily"] = ingest_daily(settings=settings, start_date=start_date, end_date=end_date, full_refresh=full_refresh)
                results["stooq_intraday"] = ingest_intraday(settings=settings, start_date=start_date, end_date=end_date, full_refresh=full_refresh)
            elif src == "alphavantage":
                from market_data.raw.ingest_alphavantage_listing_status import ingest as ingest_listing
                from market_data.raw.ingest_alphavantage_daily_adjusted import ingest as ingest_adj
                results["av_listing"] = ingest_listing(settings=settings)
                results["av_daily_adjusted"] = ingest_adj(settings=settings, start_date=start_date, end_date=end_date, symbols_file=symbols_file)
            elif src == "sec":
                from market_data.raw.ingest_sec_submissions import ingest as ingest_sub
                from market_data.raw.ingest_sec_companyfacts import ingest as ingest_facts
                results["sec_submissions"] = ingest_sub(settings=settings)
                results["sec_companyfacts"] = ingest_facts(settings=settings)
            elif src == "fred":
                from market_data.raw.ingest_fred_series import ingest as ingest_series
                from market_data.raw.ingest_fred_vintages import ingest as ingest_vint
                results["fred_series"] = ingest_series(settings=settings, start_date=start_date, end_date=end_date)
                results["fred_vintages"] = ingest_vint(settings=settings, start_date=start_date, end_date=end_date)
            else:
                log.warning("unknown source: %s", src)
            log.info("completed raw: %s", src)
        except Exception:
            log.exception("failed raw: %s", src)
            if fail_fast:
                raise

    return results
