"""Build authoritative SEC_SIC_4 instrument classification history from SEC bronze data."""
from __future__ import annotations

from typing import cast

import polars as pl

from market_data.common.classification import (
    build_effective_windows,
    load_classification_source_policy,
    load_sec_sic_crosswalk,
    normalize_sic_code,
    resolve_sector_etf_from_sic,
    validate_non_overlapping_windows,
)
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import bronze_path, silver_path
from market_data.common.schema_registry import INSTRUMENT_CLASSIFICATION_HISTORY
from market_data.common.settings import IngestionSettings

log = get_logger("silver.instrument_classification_history")


def _norm_cik(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Utf8).str.strip_chars().str.zfill(10)


def _norm_ticker(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Utf8).str.strip_chars().str.to_uppercase()


def _apply_sic_mapping(df: pl.DataFrame, crosswalk) -> pl.DataFrame:
    return df.with_columns(
        pl.col("raw_sic")
        .map_elements(
            lambda x: resolve_sector_etf_from_sic(cast(str | None, x), crosswalk),
            return_dtype=pl.Utf8,
        )
        .alias("sector_code")
    ).with_columns(pl.col("sector_code").alias("sector_name"))


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)

    policy = load_classification_source_policy(settings)
    crosswalk = load_sec_sic_crosswalk(settings)
    sym_path = silver_path("instrument_symbol_history", settings)
    sub_path = bronze_path("sec_submissions", settings) / "submissions.parquet"
    facts_path = bronze_path("sec_companyfacts", settings)

    if not sym_path.exists():
        log.warning("instrument_symbol_history not found: %s", sym_path)
        return {"rows": 0}
    if not sub_path.exists():
        log.warning("bronze sec_submissions not found: %s", sub_path)
        return {"rows": 0}

    sym = (
        read_parquet(sym_path)
        .select(["instrument_id", "normalized_source_symbol"])
        .collect()
        .with_columns(_norm_ticker("normalized_source_symbol").alias("normalized_source_symbol"))
        .unique(subset=["instrument_id", "normalized_source_symbol"])
    )
    if sym.height == 0:
        return {"rows": 0}

    submissions = (
        read_parquet(sub_path)
        .collect()
        .with_columns(
            _norm_cik("cik").alias("cik"),
            _norm_ticker("ticker_primary").alias("normalized_source_symbol"),
            pl.col("sic")
            .map_elements(normalize_sic_code, return_dtype=pl.Utf8)
            .alias("raw_sic"),
        )
        .filter(pl.col("normalized_source_symbol").is_not_null() & pl.col("raw_sic").is_not_null())
        .join(sym, on="normalized_source_symbol", how="inner")
        .select(
            "instrument_id",
            "cik",
            pl.col("filing_date").alias("effective_from"),
            "raw_sic",
            pl.lit("sec_submissions_header_sic").alias("source"),
            pl.col("loaded_at").alias("asof_timestamp"),
        )
    )

    dei_rows = pl.DataFrame()
    if facts_path.exists():
        facts = (
            read_parquet(facts_path)
            .collect()
            .with_columns(
                _norm_cik("cik").alias("cik"),
                pl.col("value")
                .map_elements(normalize_sic_code, return_dtype=pl.Utf8)
                .alias("raw_sic"),
            )
            .filter(
                (pl.col("taxonomy") == "dei")
                & (pl.col("concept") == "EntityPrimarySicNumber")
                & pl.col("filed_date").is_not_null()
                & pl.col("raw_sic").is_not_null()
            )
        )
        if facts.height > 0 and submissions.height > 0:
            cik_map = submissions.select(["instrument_id", "cik"]).unique(subset=["instrument_id", "cik"])
            dei_rows = facts.join(cik_map, on="cik", how="inner").select(
                "instrument_id",
                "cik",
                pl.col("filed_date").alias("effective_from"),
                "raw_sic",
                pl.lit("sec_dei_entity_primary_sic").alias("source"),
                pl.col("loaded_at").alias("asof_timestamp"),
            )

    combined = pl.concat([dei_rows, submissions], how="diagonal_relaxed") if submissions.height > 0 else dei_rows
    if combined.height == 0:
        log.warning("no SEC SIC classification rows after canonical symbol join")
        return {"rows": 0}

    combined = (
        combined.with_columns(pl.lit(policy.classification_system).alias("classification_system"))
        .with_columns(pl.when(pl.col("source") == "sec_dei_entity_primary_sic").then(0).otherwise(1).alias("_source_rank"))
        .sort(["instrument_id", "classification_system", "effective_from", "_source_rank", "asof_timestamp"])
        .unique(subset=["instrument_id", "classification_system", "effective_from"], keep="first")
        .drop("_source_rank")
    )

    mapped = _apply_sic_mapping(combined, crosswalk)
    windows = build_effective_windows(mapped)
    validate_non_overlapping_windows(windows)

    out = windows.select(
        "instrument_id",
        "classification_system",
        "sector_code",
        "sector_name",
        pl.col("raw_sic").alias("industry_group_code"),
        pl.col("raw_sic").alias("industry_group_name"),
        pl.lit(None).cast(pl.Utf8).alias("industry_code"),
        pl.lit(None).cast(pl.Utf8).alias("industry_name"),
        pl.lit(None).cast(pl.Utf8).alias("subindustry_code"),
        pl.lit(None).cast(pl.Utf8).alias("subindustry_name"),
        pl.col("effective_from").alias("effective_from_date"),
        pl.col("effective_to").alias("effective_to_date"),
        "source",
        pl.col("asof_timestamp").alias("ingested_at_utc"),
    )
    for col, dtype in INSTRUMENT_CLASSIFICATION_HISTORY.items():
        if out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(cast(pl.DataType, dtype)))
    out = validate_contract_df("instrument_classification_history", out)

    out_path = silver_path("instrument_classification_history", settings) / "instrument_classification_history.parquet"
    written = write_parquet(out, out_path)
    log.info("instrument_classification_history: %d rows -> %s", written, out_path)
    return {"rows": written}
