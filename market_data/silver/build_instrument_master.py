"""Build canonical instrument_master from Alpha Vantage listings and benchmark metadata."""
from __future__ import annotations

from datetime import date
from typing import cast

import polars as pl

from market_data.common.benchmarks import BenchmarkDef, load_benchmark_defs
from market_data.common.dates import today_utc, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import bronze_path, silver_path
from market_data.common.schema_registry import INSTRUMENT_MASTER
from market_data.common.settings import IngestionSettings
from market_data.silver.sid_registry import assign_sids

log = get_logger("silver.instrument_master")


def _asset_security_types(asset_type: str | None, benchmark_type: str | None) -> tuple[str, str]:
    at = (asset_type or "").strip().lower()
    bt = (benchmark_type or "").strip().lower()
    if bt == "volatility_index":
        return "index", "index"
    if bt == "volatility_etp":
        return "fund", "etp_proxy"
    if bt in {"market", "duration", "credit", "sector", "commodity"}:
        return "fund", "etf"
    if at == "etf":
        return "fund", "etf"
    if at == "stock":
        return "equity", "common_stock"
    if at == "index":
        return "index", "index"
    return at or "unknown", at or "unknown"


def _benchmark_seed_rows(benchmarks: list[BenchmarkDef], existing_symbols: set[str], now_date: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for b in benchmarks:
        if b.symbol in existing_symbols:
            continue
        asset_type, security_type = _asset_security_types(None, b.benchmark_type)
        exchange = "CBOE" if b.symbol.startswith("^") else "NYSE ARCA"
        rows.append({
            "symbol": b.symbol,
            "name": b.symbol,
            "exchange": exchange,
            "asset_type_raw": asset_type,
            "status": "active",
            "ipo_date": now_date,
            "delist_date": None,
            "source_priority": 2,
            "source": "benchmark_config",
        })
    return rows


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)
    bronze_file = bronze_path("av_listing_status", settings) / "listing_status.parquet"
    if not bronze_file.exists():
        log.warning("bronze listing_status not found: %s", bronze_file)
        return {"rows": 0}

    now = utc_now()
    now_date = now.date()

    av = read_parquet(bronze_file).collect()
    if len(av) == 0:
        return {"rows": 0}

    base = av.select(
        pl.col("symbol"),
        pl.col("name").fill_null(pl.col("symbol")).alias("name"),
        pl.col("exchange"),
        pl.col("asset_type").alias("asset_type_raw"),
        pl.col("status"),
        pl.col("ipo_date"),
        pl.col("delist_date"),
        pl.lit(1).cast(pl.Int32).alias("source_priority"),
        pl.lit("alphavantage").alias("source"),
    )

    existing_symbols = set(base.get_column("symbol").to_list())
    benchmark_rows = _benchmark_seed_rows(load_benchmark_defs(settings), existing_symbols, now_date)
    if benchmark_rows:
        base = pl.concat([base, pl.DataFrame(benchmark_rows)], how="diagonal_relaxed")

    base = base.sort(["exchange", "symbol", "status", "name"]).unique(
        subset=["exchange", "symbol", "status", "name"],
        keep="first",
    )

    keyed = base.select(
        pl.col("exchange"),
        pl.col("symbol"),
        pl.col("status"),
        pl.col("name"),
    )
    keyed = assign_sids(keyed, settings).rename({"sid": "instrument_id"})
    out = base.join(keyed, on=["exchange", "symbol", "status", "name"], how="left")

    out = out.with_columns(
        pl.struct(["asset_type_raw"]).map_elements(
            lambda r: _asset_security_types(r["asset_type_raw"], None)[0], return_dtype=pl.Utf8
        ).alias("asset_type"),
        pl.struct(["asset_type_raw", "symbol"]).map_elements(
            lambda r: _asset_security_types(r["asset_type_raw"], "volatility_index" if str(r["symbol"]).startswith("^") else None)[1],
            return_dtype=pl.Utf8,
        ).alias("security_type"),
        pl.col("symbol").alias("canonical_symbol"),
        pl.col("name").alias("legal_name"),
        pl.lit("US").alias("primary_country"),
        pl.lit("USD").alias("currency"),
        (pl.col("status").str.to_lowercase() == "active").alias("is_active_current"),
        pl.coalesce(pl.col("ipo_date"), pl.lit(now_date)).alias("first_seen_date"),
        pl.coalesce(pl.col("delist_date"), pl.lit(now_date)).alias("last_seen_date"),
        pl.lit(now).alias("created_at_utc"),
        pl.lit(now).alias("updated_at_utc"),
    )

    out = out.select(list(INSTRUMENT_MASTER.keys()))
    for col, dtype in INSTRUMENT_MASTER.items():
        if out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(cast(pl.DataType, dtype)))
    out = validate_contract_df("instrument_master", out)

    out_dir = silver_path("instrument_master", settings)
    out_path = out_dir / "instrument_master.parquet"
    written = write_parquet(out, out_path)
    log.info("instrument_master: %d rows -> %s", written, out_path)
    return {"rows": written, "benchmarks_seeded": len(benchmark_rows)}
