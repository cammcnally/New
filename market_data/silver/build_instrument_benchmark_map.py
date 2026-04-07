"""Build deterministic benchmark_id mappings for eligible U.S. equities."""
from __future__ import annotations

from typing import cast

import polars as pl

from market_data.common.benchmarks import derive_benchmark_id
from market_data.common.classification import build_effective_windows, validate_non_overlapping_windows
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import silver_path
from market_data.common.schema_registry import INSTRUMENT_BENCHMARK_MAP
from market_data.common.settings import IngestionSettings

log = get_logger("silver.instrument_benchmark_map")

_MARKET_BENCHMARK_ID = derive_benchmark_id("SPY")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)
    im_path = silver_path("instrument_master", settings) / "instrument_master.parquet"
    cls_path = silver_path("instrument_classification_history", settings)

    if not im_path.exists():
        log.warning("instrument_master not found: %s", im_path)
        return {"rows": 0}

    im = (
        read_parquet(im_path)
        .collect()
        .filter((pl.col("asset_type") == "equity") & (pl.col("primary_country") == "US"))
        .select(
            "instrument_id",
            pl.col("first_seen_date").alias("effective_from"),
            pl.when(pl.col("is_active_current")).then(pl.lit(None).cast(pl.Date)).otherwise(pl.col("last_seen_date")).alias("effective_to"),
            pl.col("updated_at_utc").alias("asof_timestamp"),
        )
    )
    if im.height == 0:
        return {"rows": 0}

    base = im.with_columns(
        pl.lit("SEC_SIC_4").alias("classification_system"),
        pl.lit(_MARKET_BENCHMARK_ID).alias("market_benchmark_id"),
        pl.lit(None).cast(pl.Utf8).alias("sector_benchmark_id"),
        pl.lit("benchmark_map_sec_sic4_v1").alias("mapping_rule_version"),
        pl.lit("instrument_master_default_spy").alias("mapping_source"),
    )

    if cls_path.exists():
        cls = (
            read_parquet(cls_path)
            .select(
                "instrument_id",
                pl.col("sector_code"),
                pl.col("effective_from_date").alias("effective_from"),
                pl.col("effective_to_date").alias("effective_to"),
                pl.col("ingested_at_utc").alias("asof_timestamp"),
            )
            .collect()
            .filter(pl.col("instrument_id").is_in(im["instrument_id"].to_list()))
            .with_columns(
                pl.col("sector_code")
                .map_elements(
                    lambda x: derive_benchmark_id(cast(str, x)) if x is not None else None,
                    return_dtype=pl.Utf8,
                )
                .alias("sector_benchmark_id"),
                pl.lit("SEC_SIC_4").alias("classification_system"),
                pl.lit(_MARKET_BENCHMARK_ID).alias("market_benchmark_id"),
                pl.lit("benchmark_map_sec_sic4_v1").alias("mapping_rule_version"),
                pl.lit("sec_sic4_crosswalk").alias("mapping_source"),
            )
            .drop("sector_code")
        )
    else:
        cls = pl.DataFrame()

    classified_ids = set(cls["instrument_id"].to_list()) if cls.height > 0 else set()
    unmapped = base.filter(~pl.col("instrument_id").is_in(list(classified_ids)))
    combined = pl.concat([cls, unmapped], how="diagonal_relaxed") if cls.height > 0 else unmapped

    windows = build_effective_windows(combined)
    validate_non_overlapping_windows(windows)

    out = windows.select(
        "instrument_id",
        "market_benchmark_id",
        "sector_benchmark_id",
        pl.col("effective_from").alias("effective_from_date"),
        pl.col("effective_to").alias("effective_to_date"),
        "mapping_rule_version",
        "mapping_source",
        "asof_timestamp",
    )
    for col, dtype in INSTRUMENT_BENCHMARK_MAP.items():
        if out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(cast(pl.DataType, dtype)))
    out = validate_contract_df("instrument_benchmark_map", out)

    out_path = silver_path("instrument_benchmark_map", settings) / "instrument_benchmark_map.parquet"
    written = write_parquet(out, out_path)
    log.info("instrument_benchmark_map: %d rows -> %s", written, out_path)
    return {"rows": written}
