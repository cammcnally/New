"""Orchestrate bronze-layer normalization."""
from __future__ import annotations

from market_data.common.source_catalog import enabled_bronze_datasets
from market_data.common.logging import get_logger
from market_data.common.settings import IngestionSettings

log = get_logger("orchestration.bronze")

_NORMALIZERS = {
    "yfinance_daily": "market_data.bronze.normalize_yfinance_daily",
    "stooq_daily": "market_data.bronze.normalize_stooq_daily",
    "stooq_intraday": "market_data.bronze.normalize_stooq_intraday",
    "av_listing_status": "market_data.bronze.normalize_alphavantage_listing_status",
    "av_daily_adjusted": "market_data.bronze.normalize_alphavantage_daily_adjusted",
    "sec_company_tickers": "market_data.bronze.normalize_sec_company_tickers",
    "sec_submissions": "market_data.bronze.normalize_sec_submissions",
    "sec_companyfacts": "market_data.bronze.normalize_sec_companyfacts",
    "fred_observations": "market_data.bronze.normalize_fred_observations",
    "fred_vintages": "market_data.bronze.normalize_fred_vintages",
}


def available_datasets(settings: IngestionSettings) -> tuple[str, ...]:
    return enabled_bronze_datasets(settings)


def run_bronze(
    *,
    settings: IngestionSettings,
    dataset: str = "all",
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
    fail_fast: bool = False,
) -> dict[str, object]:
    datasets = available_datasets(settings) if dataset == "all" else (dataset,)
    results: dict[str, object] = {}

    for ds in datasets:
        log.info("normalizing bronze: %s", ds)
        try:
            import importlib
            mod = importlib.import_module(_NORMALIZERS[ds])
            results[ds] = mod.normalize(
                settings=settings,
                start_date=start_date,
                end_date=end_date,
                full_refresh=full_refresh,
            )
            log.info("completed bronze: %s", ds)
        except Exception:
            log.exception("failed bronze: %s", ds)
            if fail_fast:
                raise

    return results
