"""Orchestrate silver-layer builds in dependency order."""
from __future__ import annotations

from market_data.common.logging import get_logger
from market_data.common.settings import IngestionSettings

log = get_logger("orchestration.silver")

SILVER_BUILD_ORDER = [
    "instrument_master",
    "instrument_symbol_history",
    "benchmark_definitions",
    "security_master",
    "symbol_map_history",
    "prices_1d_unadjusted",
    "corporate_actions",
    "adjustment_factors",
    "prices_1d_split_adjusted",
    "filings",
    "fundamentals_reported",
    "fundamentals_asof_daily",
    "instrument_classification_history",
    "instrument_benchmark_map",
    "macro_observations_vintage",
    "macro_asof_daily",
    "universe_membership",
    "benchmark_prices_daily",
    "trading_calendar",
]

_BUILDERS = {
    "instrument_master": "market_data.silver.build_instrument_master",
    "instrument_symbol_history": "market_data.silver.build_instrument_symbol_history",
    "benchmark_definitions": "market_data.silver.build_benchmark_definitions",
    "security_master": "market_data.silver.compat_security_master",
    "symbol_map_history": "market_data.silver.build_symbol_map_history",
    "prices_1d_unadjusted": "market_data.silver.build_prices_1d_unadjusted",
    "corporate_actions": "market_data.silver.build_corporate_actions",
    "adjustment_factors": "market_data.silver.build_adjustment_factors",
    "prices_1d_split_adjusted": "market_data.silver.build_prices_1d_split_adjusted",
    "filings": "market_data.silver.build_filings",
    "fundamentals_reported": "market_data.silver.build_fundamentals_reported",
    "fundamentals_asof_daily": "market_data.silver.build_fundamentals_asof_daily",
    "instrument_classification_history": "market_data.silver.build_instrument_classification_history",
    "instrument_benchmark_map": "market_data.silver.build_instrument_benchmark_map",
    "macro_observations_vintage": "market_data.silver.build_macro_observations_vintage",
    "macro_asof_daily": "market_data.silver.build_macro_asof_daily",
    "universe_membership": "market_data.silver.build_universe_membership",
    "benchmark_prices_daily": "market_data.silver.build_benchmark_prices_daily",
    "trading_calendar": "market_data.silver.build_trading_calendar",
}


def run_silver(
    *,
    settings: IngestionSettings,
    dataset: str = "all",
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
    fail_fast: bool = False,
) -> dict[str, object]:
    if dataset == "all":
        datasets = SILVER_BUILD_ORDER
    else:
        datasets = [dataset]

    results: dict[str, object] = {}
    for ds in datasets:
        log.info("building silver: %s", ds)
        try:
            import importlib
            mod = importlib.import_module(_BUILDERS[ds])
            results[ds] = mod.build(
                settings=settings,
                start_date=start_date,
                end_date=end_date,
                full_refresh=full_refresh,
            )
            log.info("completed silver: %s", ds)
        except Exception:
            log.exception("failed silver: %s", ds)
            if fail_fast:
                raise

    return results
