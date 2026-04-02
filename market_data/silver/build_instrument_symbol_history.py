"""Build canonical instrument_symbol_history from instrument_master and source listings.

This is an initial canonical mapping layer, not complete historical symbology.
Full historical ticker-change coverage is not yet guaranteed without a dedicated
historical symbol source.
"""
from __future__ import annotations

from typing import cast

import polars as pl

from market_data.common.benchmarks import benchmark_symbols
from market_data.common.dates import utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import bronze_path, silver_path
from market_data.common.schema_registry import INSTRUMENT_SYMBOL_HISTORY
from market_data.common.settings import IngestionSettings

log = get_logger("silver.instrument_symbol_history")
_LISTING_STATUS_SOURCES = ("alphavantage", "yfinance")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)
    im_path = silver_path("instrument_master", settings) / "instrument_master.parquet"
    bronze_file = bronze_path("av_listing_status", settings) / "listing_status.parquet"
    if not im_path.exists():
        log.warning("instrument_master not found: %s", im_path)
        return {"rows": 0}

    im = read_parquet(im_path).collect()
    now = utc_now()

    frames: list[pl.DataFrame] = []
    if bronze_file.exists():
        av = read_parquet(bronze_file).collect().with_columns(
            pl.col("status").str.to_lowercase().eq("active").alias("__status_is_active")
        )
        listing_map = av.join(
            im.select(
                "instrument_id",
                "canonical_symbol",
                "exchange",
                "legal_name",
                pl.col("is_active_current").alias("__status_is_active"),
            ),
            left_on=["symbol", "exchange", "name", "__status_is_active"],
            right_on=["canonical_symbol", "exchange", "legal_name", "__status_is_active"],
            how="inner",
        ).select(
            "instrument_id",
            pl.col("symbol").alias("raw_source_symbol"),
            pl.col("symbol").str.to_uppercase().alias("normalized_source_symbol"),
            pl.coalesce(pl.col("ipo_date"), pl.lit(now.date())).alias("effective_from_date"),
            pl.col("delist_date").alias("effective_to_date"),
            pl.lit(True).alias("is_primary_for_source"),
            pl.lit(now).alias("ingested_at_utc"),
        )
        for source_name in _LISTING_STATUS_SOURCES:
            frames.append(
                listing_map.with_columns(pl.lit(source_name).alias("source")).select(
                    "instrument_id",
                    "source",
                    "raw_source_symbol",
                    "normalized_source_symbol",
                    "effective_from_date",
                    "effective_to_date",
                    "is_primary_for_source",
                    "ingested_at_utc",
                )
            )

    benchmark_syms = benchmark_symbols(settings)
    bench = im.filter(pl.col("canonical_symbol").is_in(benchmark_syms)).select(
        "instrument_id",
        pl.lit("benchmark_config").alias("source"),
        pl.col("canonical_symbol").alias("raw_source_symbol"),
        pl.col("canonical_symbol").str.to_uppercase().alias("normalized_source_symbol"),
        pl.col("first_seen_date").alias("effective_from_date"),
        pl.lit(None).cast(pl.Date).alias("effective_to_date"),
        pl.lit(True).alias("is_primary_for_source"),
        pl.lit(now).alias("ingested_at_utc"),
    )
    if len(bench) > 0:
        frames.append(bench)

    if not frames:
        return {"rows": 0}

    out = pl.concat(frames, how="diagonal_relaxed").sort(
        ["source", "raw_source_symbol", "effective_from_date", "instrument_id"]
    ).unique(
        subset=["instrument_id", "source", "raw_source_symbol", "effective_from_date"],
        keep="first",
    )

    out = out.select(list(INSTRUMENT_SYMBOL_HISTORY.keys()))
    for col, dtype in INSTRUMENT_SYMBOL_HISTORY.items():
        if out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(cast(pl.DataType, dtype)))
    out = validate_contract_df("instrument_symbol_history", out)

    out_path = silver_path("instrument_symbol_history", settings) / "instrument_symbol_history.parquet"
    written = write_parquet(out, out_path)
    log.info("instrument_symbol_history: %d rows -> %s", written, out_path)
    return {"rows": written}
