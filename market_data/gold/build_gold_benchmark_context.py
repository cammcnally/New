"""Gold mart: wide-format benchmark price context using compatibility identity."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import gold_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("gold.benchmark_context")

_PIVOT_FIELDS = ["open", "high", "low", "close", "volume"]


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)

    bench_dir = silver_path("benchmark_prices_daily", settings)
    master_dir = silver_path("security_master", settings)

    for name, path in [
        ("benchmark_prices_daily", bench_dir),
        ("compat security_master", master_dir),
    ]:
        if not path.exists():
            log.warning("silver %s not found: %s", name, path)
            return {"rows": 0}

    out_dir = gold_path("gold_benchmark_context", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    bench = (
        read_parquet(bench_dir)
        .filter((pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed))
        .collect()
    )
    if len(bench) == 0:
        log.warning("no benchmark prices in date range")
        return {"rows": 0}

    master = (
        read_parquet(master_dir)
        .select("sid", "symbol_current")
        .collect()
    )
    bench = bench.join(master, on="sid", how="left")

    dfs: list[pl.DataFrame] = []
    for field in _PIVOT_FIELDS:
        pivoted = bench.pivot(
            on="symbol_current",
            index="trade_date",
            values=field,
        )
        renamed = {
            c: f"{c}_{field}"
            for c in pivoted.columns
            if c != "trade_date"
        }
        dfs.append(pivoted.rename(renamed))

    result = dfs[0]
    for other in dfs[1:]:
        result = result.join(other, on="trade_date", how="outer_coalesce")

    result = result.sort("trade_date").with_columns(
        pl.col("trade_date").dt.year().alias("year")
    )

    rows = write_parquet(result, out_dir, partition_by=["year"])
    log.info("gold_benchmark_context: %d rows -> %s", rows, out_dir)
    return {"rows": rows}
