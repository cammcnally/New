"""Orchestrate gold-layer mart builds."""
from __future__ import annotations

from market_data.common.logging import get_logger
from market_data.common.settings import IngestionSettings

log = get_logger("orchestration.gold")

GOLD_BUILD_ORDER = [
    "daily_panel",
    "intraday_panel",
    "macro_context",
    "benchmark_context",
    "feature_base",
]

_BUILDERS = {
    "daily_panel": "market_data.gold.build_gold_daily_panel",
    "intraday_panel": "market_data.gold.build_gold_intraday_panel",
    "macro_context": "market_data.gold.build_gold_macro_context",
    "benchmark_context": "market_data.gold.build_gold_benchmark_context",
    "feature_base": "market_data.gold.build_gold_feature_base",
}


def run_gold(
    *,
    settings: IngestionSettings,
    dataset: str = "all",
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
    fail_fast: bool = False,
) -> dict[str, object]:
    datasets = GOLD_BUILD_ORDER if dataset == "all" else [dataset]
    results: dict[str, object] = {}

    for ds in datasets:
        log.info("building gold: %s", ds)
        try:
            import importlib
            mod = importlib.import_module(_BUILDERS[ds])
            results[ds] = mod.build(
                settings=settings,
                start_date=start_date,
                end_date=end_date,
                full_refresh=full_refresh,
            )
            log.info("completed gold: %s", ds)
        except Exception:
            log.exception("failed gold: %s", ds)
            if fail_fast:
                raise

    return results
