"""Build silver benchmark_prices_daily for configured benchmark symbols."""
from __future__ import annotations

import polars as pl

from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings, load_yaml_config

log = get_logger("silver.benchmark_prices_daily")


def _flatten_benchmark_symbols(cfg: dict) -> list[str]:
    root = cfg.get("benchmarks") or {}
    out: list[str] = []
    for _group, entries in root.items():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("symbol"):
                    out.append(str(entry["symbol"]).strip())
    return sorted(set(out))


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = full_refresh

    sd = parse_date(start_date)
    ed = parse_date(end_date)

    cfg = load_yaml_config("benchmarks.yaml", settings)
    symbols = _flatten_benchmark_symbols(cfg)
    if not symbols:
        log.warning("benchmarks.yaml has no symbols")
        return {"rows": 0}

    prices_path = silver_path("prices_1d_unadjusted", settings)
    master_path = silver_path("instrument_master", settings)
    if not prices_path.exists() or not master_path.exists():
        log.warning("missing silver inputs: prices=%s master=%s", prices_path, master_path)
        return {"rows": 0}

    master = read_parquet(master_path).filter(pl.col("canonical_symbol").is_in(symbols)).select(
        pl.col("instrument_id").cast(pl.Utf8).alias("sid"),
        pl.col("canonical_symbol").alias("symbol"),
    )
    sids = master.select("sid").unique()

    lf = (
        read_parquet(prices_path)
        .filter((pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed))
        .join(sids.lazy(), on="sid", how="inner")
        .select(
            "sid",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source_vendor",
            "loaded_at",
        )
    )

    df = lf.collect()
    if len(df) == 0:
        log.warning("no benchmark price rows in range")
        return {"rows": 0}

    df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
    out_dir = silver_path("benchmark_prices_daily", settings)
    written = write_parquet(df, out_dir, partition_by=["year"])
    log.info("silver benchmark_prices_daily: %d rows -> %s", written, out_dir)
    return {"rows": written}
