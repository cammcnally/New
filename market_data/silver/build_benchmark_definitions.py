"""Build canonical benchmark_definitions from benchmark configuration."""
from __future__ import annotations

import polars as pl

from market_data.common.benchmarks import load_benchmark_defs
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.benchmark_definitions")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)

    rows = [
        {
            "benchmark_id": item.benchmark_id,
            "group": item.group,
            "symbol": item.symbol,
            "benchmark_type": item.benchmark_type,
            "semantic_role": item.semantic_role,
            "default_usage": item.default_usage,
            "proxy_for": item.proxy_for,
            "canonical_or_proxy": item.canonical_or_proxy,
        }
        for item in load_benchmark_defs(settings)
    ]
    if not rows:
        log.warning("no benchmark definitions configured")
        return {"rows": 0}

    df = validate_contract_df("benchmark_definitions", pl.DataFrame(rows))
    out_path = silver_path("benchmark_definitions", settings) / "benchmark_definitions.parquet"
    written = write_parquet(df, out_path)
    log.info("silver benchmark_definitions: %d rows -> %s", written, out_path)
    return {"rows": written}
