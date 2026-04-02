"""Silver: daily OHLCV from bronze price data joined to canonical identity.

Reads from whichever bronze price table exists (yfinance or stooq).
"""
from __future__ import annotations

import json
import shutil
from typing import cast

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import bronze_path, qa_dir, silver_path
from market_data.common.schema_registry import PRICES_1D_UNADJUSTED
from market_data.common.settings import IngestionSettings

log = get_logger("silver.prices_1d_unadjusted")

_BRONZE_SOURCES = ["yfinance_prices_1d", "stooq_prices_1d"]
_BRONZE_TO_SYMBOL_SOURCE = {
    "yfinance_prices_1d": "yfinance",
    "stooq_prices_1d": "stooq",
}


def _write_unresolved_identity_report(
    *,
    settings: IngestionSettings,
    source_name: str | None,
    canonical_symbol_history_present: bool,
    unresolved: pl.DataFrame,
) -> str:
    report_path = qa_dir(settings) / "unresolved_identity_prices_1d.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "source": source_name,
            "canonical_symbol_history_present": canonical_symbol_history_present,
            "unresolved_rows": len(unresolved),
        },
        "sample_rows": unresolved.head(100).to_dicts(),
    }
    report_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(report_path)


def _invalid_ohlc_expr() -> pl.Expr:
    return (
        (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("low") > pl.col("high"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
    )


def _write_invalid_ohlc_report(
    *,
    settings: IngestionSettings,
    source_name: str | None,
    invalid_rows: pl.DataFrame,
) -> str:
    report_path = qa_dir(settings) / "invalid_ohlc_prices_1d.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "source": source_name,
            "invalid_ohlc_rows": len(invalid_rows),
        },
        "sample_rows": invalid_rows.head(100).with_columns(
            pl.col("trade_date").cast(pl.Utf8)
        ).to_dicts(),
    }
    report_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(report_path)


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    ish_path = silver_path("instrument_symbol_history", settings)
    out_dir = silver_path("prices_1d_unadjusted", settings)

    bronze_dir = None
    source_name = None
    for src in _BRONZE_SOURCES:
        candidate = bronze_path(src, settings)
        if candidate.exists():
            bronze_dir = candidate
            source_name = _BRONZE_TO_SYMBOL_SOURCE[src]
            log.info("using bronze source: %s", src)
            break

    if bronze_dir is None:
        log.warning("no bronze price data found (tried: %s)", _BRONZE_SOURCES)
        return {"rows": 0}

    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    base = read_parquet(bronze_dir).filter(
        (pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed)
    ).collect()

    base = base.with_row_index("row_id").with_columns(
        pl.col("symbol").str.to_uppercase().alias("join_symbol"),
    )
    if base.is_empty():
        return {"rows": 0, "unresolved_rows": 0, "used_security_master_fallback": False}

    if not ish_path.exists():
        unresolved_report_path = _write_unresolved_identity_report(
            settings=settings,
            source_name=source_name,
            canonical_symbol_history_present=False,
            unresolved=base.select(
                "symbol",
                "trade_date",
                "source_vendor",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ),
        )
        log.warning("instrument_symbol_history not found; canonical price attribution failed closed")
        return {
            "rows": 0,
            "unresolved_rows": len(base),
            "used_security_master_fallback": False,
            "unresolved_identity_report": unresolved_report_path,
        }

    ish = (
        read_parquet(ish_path)
        .filter(pl.col("source") == source_name)
        .select(
            pl.col("instrument_id").cast(pl.Utf8).alias("sid"),
            pl.col("normalized_source_symbol").alias("join_symbol"),
            "effective_from_date",
            "effective_to_date",
        )
        .collect()
    )
    joined = base.join(ish, on="join_symbol", how="left")
    matched = joined.filter(
        pl.col("sid").is_not_null()
        & (pl.col("trade_date") >= pl.col("effective_from_date"))
        & (
            pl.col("effective_to_date").is_null()
            | (pl.col("trade_date") <= pl.col("effective_to_date"))
        )
    )
    matched_row_ids = matched.select("row_id").unique()
    unresolved = (
        base.join(matched_row_ids, on="row_id", how="anti")
        .select("symbol", "trade_date", "source_vendor", "open", "high", "low", "close", "volume")
    )
    unresolved_report_path = _write_unresolved_identity_report(
        settings=settings,
        source_name=source_name,
        canonical_symbol_history_present=True,
        unresolved=unresolved,
    )

    df = (
        matched.with_columns(
            pl.col("symbol").alias("source_symbol"),
            pl.lit(utc_now()).alias("loaded_at"),
        )
        .select([
            "sid", "trade_date", "open", "high", "low", "close", "volume",
            "source_vendor", "source_symbol", "loaded_at",
        ])
        .with_columns(pl.col("trade_date").dt.year().alias("year"))
    )
    invalid_ohlc = df.filter(_invalid_ohlc_expr()).select(
        "sid",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source_vendor",
        "source_symbol",
    )
    invalid_ohlc_rows = len(invalid_ohlc)
    invalid_ohlc_report = None
    if invalid_ohlc_rows:
        invalid_ohlc_report = _write_invalid_ohlc_report(
            settings=settings,
            source_name=source_name,
            invalid_rows=invalid_ohlc,
        )
        df = df.filter(~_invalid_ohlc_expr())
        log.warning("quarantined %d invalid OHLC rows from %s source data", invalid_ohlc_rows, source_name)
    else:
        (qa_dir(settings) / "invalid_ohlc_prices_1d.json").unlink(missing_ok=True)
    for col, dtype in PRICES_1D_UNADJUSTED.items():
        if col in df.columns and df.schema[col] != dtype:
            df = df.with_columns(pl.col(col).cast(cast(pl.DataType, dtype)))
    if df.is_empty():
        return {
            "rows": 0,
            "unresolved_rows": len(unresolved),
            "used_security_master_fallback": False,
            "unresolved_identity_report": unresolved_report_path,
            "invalid_ohlc_rows": invalid_ohlc_rows,
            "invalid_ohlc_report": invalid_ohlc_report,
        }
    df = validate_contract_df("prices_1d_unadjusted", df)

    rows = write_parquet(df, out_dir, partition_by=["year"])
    unresolved_rows = len(unresolved)
    log.info("silver prices_1d_unadjusted: %d rows, unresolved_identity=%d", rows, unresolved_rows)
    return {
        "rows": rows,
        "unresolved_rows": unresolved_rows,
        "used_security_master_fallback": False,
        "unresolved_identity_report": unresolved_report_path,
        "invalid_ohlc_rows": invalid_ohlc_rows,
        "invalid_ohlc_report": invalid_ohlc_report,
    }
