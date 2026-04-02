"""Canonical schema definitions for all ingestion-layer tables.

This file now contains two layers:

1. Canonical production data-contract tables
2. Deprecated compatibility schemas kept temporarily so existing pipeline
   integrations keep working while the repo migrates to `instrument_master`

Rules:
- `instrument_master` is canonical
- `security_master` is compatibility-only and must be auto-generated
- Ticker is never the economic identity key
"""
from __future__ import annotations

import polars as pl


# ── Canonical instrument model ───────────────────────────────────────────────

INSTRUMENT_MASTER_PK = ["instrument_id"]
INSTRUMENT_MASTER = {
    "instrument_id": pl.Int64,
    "asset_type": pl.Utf8,
    "security_type": pl.Utf8,
    "canonical_symbol": pl.Utf8,
    "legal_name": pl.Utf8,
    "exchange": pl.Utf8,
    "primary_country": pl.Utf8,
    "currency": pl.Utf8,
    "is_active_current": pl.Boolean,
    "first_seen_date": pl.Date,
    "last_seen_date": pl.Date,
    "source_priority": pl.Int32,
    "created_at_utc": pl.Datetime("us", "UTC"),
    "updated_at_utc": pl.Datetime("us", "UTC"),
}

INSTRUMENT_SYMBOL_HISTORY_PK = [
    "instrument_id",
    "source",
    "raw_source_symbol",
    "effective_from_date",
]
INSTRUMENT_SYMBOL_HISTORY = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "normalized_source_symbol": pl.Utf8,
    "effective_from_date": pl.Date,
    "effective_to_date": pl.Date,
    "is_primary_for_source": pl.Boolean,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}


# ── Canonical price contracts ────────────────────────────────────────────────

PRICES_1D_UNADJUSTED_V2_PK = ["instrument_id", "source", "trade_date"]
PRICES_1D_UNADJUSTED_V2 = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "trade_date": pl.Date,
    "session_open_ts_utc": pl.Datetime("us", "UTC"),
    "session_close_ts_utc": pl.Datetime("us", "UTC"),
    "exchange_timezone": pl.Utf8,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "adj_close": pl.Float64,
    "volume": pl.Float64,
    "currency": pl.Utf8,
    "source_last_updated_at_utc": pl.Datetime("us", "UTC"),
    "ingested_at_utc": pl.Datetime("us", "UTC"),
    "is_delisted_observation": pl.Boolean,
    "quality_flags": pl.List(pl.Utf8),
}

PRICES_30M_UNADJUSTED_V2_PK = ["instrument_id", "source", "session_close_ts_utc"]
PRICES_30M_UNADJUSTED_V2 = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "trade_date": pl.Date,
    "session_open_ts_utc": pl.Datetime("us", "UTC"),
    "session_close_ts_utc": pl.Datetime("us", "UTC"),
    "exchange_timezone": pl.Utf8,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "currency": pl.Utf8,
    "source_last_updated_at_utc": pl.Datetime("us", "UTC"),
    "ingested_at_utc": pl.Datetime("us", "UTC"),
    "quality_flags": pl.List(pl.Utf8),
}

PRICES_1D_SPLIT_ADJUSTED_V2_PK = ["instrument_id", "source", "trade_date"]
PRICES_1D_SPLIT_ADJUSTED_V2 = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "cum_split_factor": pl.Float64,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}

PRICES_1D_TOTAL_RETURN_V2_PK = ["instrument_id", "source", "trade_date"]
PRICES_1D_TOTAL_RETURN_V2 = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "cum_total_return_factor": pl.Float64,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}


# ── Corporate actions ────────────────────────────────────────────────────────

CORPORATE_ACTIONS_PK = ["instrument_id", "action_type", "ex_date", "source"]
CORPORATE_ACTIONS = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "action_type": pl.Utf8,
    "ex_date": pl.Date,
    "cash_amount": pl.Float64,
    "split_coefficient": pl.Float64,
    "record_date": pl.Date,
    "payment_date": pl.Date,
    "declared_date": pl.Date,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}

ADJUSTMENT_FACTORS_PK = ["instrument_id", "effective_date"]
ADJUSTMENT_FACTORS = {
    "instrument_id": pl.Int64,
    "effective_date": pl.Date,
    "split_factor": pl.Float64,
    "dividend_factor": pl.Float64,
    "cum_split_factor": pl.Float64,
    "cum_total_return_factor": pl.Float64,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}


# ── Canonical macro PIT model ────────────────────────────────────────────────

MACRO_OBSERVATIONS_VINTAGE_PK = ["series_id", "observation_date", "vintage_date"]
MACRO_OBSERVATIONS_VINTAGE = {
    "series_id": pl.Utf8,
    "observation_date": pl.Date,
    "value": pl.Float64,
    "vintage_date": pl.Date,
    "release_ts_utc": pl.Datetime("us", "UTC"),
    "available_from_ts_utc": pl.Datetime("us", "UTC"),
    "available_to_ts_utc": pl.Datetime("us", "UTC"),
    "source": pl.Utf8,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}

MACRO_ASOF_DAILY_PK = ["series_id", "asof_date", "observation_date"]
MACRO_ASOF_DAILY = {
    "series_id": pl.Utf8,
    "asof_date": pl.Date,
    "observation_date": pl.Date,
    "value": pl.Float64,
    "selected_vintage_date": pl.Date,
    "selected_available_from_ts_utc": pl.Datetime("us", "UTC"),
    "selection_rule_version": pl.Utf8,
    "built_at_utc": pl.Datetime("us", "UTC"),
}


# ── Fundamentals contract (schema stub may be empty initially) ──────────────

FUNDAMENTALS_PUBLIC_FACTS_PK = ["instrument_id", "accession_number", "metric_name"]
FUNDAMENTALS_PUBLIC_FACTS = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "cik": pl.Utf8,
    "accession_number": pl.Utf8,
    "statement_type": pl.Utf8,
    "fiscal_period_end": pl.Date,
    "fiscal_period_type": pl.Utf8,
    "filing_date": pl.Date,
    "acceptance_datetime_utc": pl.Datetime("us", "UTC"),
    "public_availability_ts_utc": pl.Datetime("us", "UTC"),
    "amendment_flag": pl.Boolean,
    "metric_name": pl.Utf8,
    "metric_value": pl.Float64,
    "unit": pl.Utf8,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}


# ── Classification and benchmark alignment ───────────────────────────────────

BENCHMARK_DEFINITIONS_PK = ["symbol"]
BENCHMARK_DEFINITIONS = {
    "group": pl.Utf8,
    "symbol": pl.Utf8,
    "benchmark_type": pl.Utf8,
    "semantic_role": pl.Utf8,
    "default_usage": pl.Utf8,
    "proxy_for": pl.Utf8,
    "canonical_or_proxy": pl.Utf8,
}

INSTRUMENT_CLASSIFICATION_HISTORY_PK = [
    "instrument_id",
    "classification_system",
    "effective_from_date",
]
INSTRUMENT_CLASSIFICATION_HISTORY = {
    "instrument_id": pl.Int64,
    "classification_system": pl.Utf8,
    "sector_code": pl.Utf8,
    "sector_name": pl.Utf8,
    "industry_group_code": pl.Utf8,
    "industry_group_name": pl.Utf8,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "subindustry_code": pl.Utf8,
    "subindustry_name": pl.Utf8,
    "effective_from_date": pl.Date,
    "effective_to_date": pl.Date,
    "source": pl.Utf8,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}

INSTRUMENT_BENCHMARK_MAP_PK = [
    "instrument_id",
    "mapping_type",
    "benchmark_instrument_id",
    "effective_from_date",
]
INSTRUMENT_BENCHMARK_MAP = {
    "instrument_id": pl.Int64,
    "mapping_type": pl.Utf8,
    "benchmark_instrument_id": pl.Int64,
    "classification_system": pl.Utf8,
    "mapping_confidence": pl.Float64,
    "effective_from_date": pl.Date,
    "effective_to_date": pl.Date,
    "mapping_rule_version": pl.Utf8,
    "created_at_utc": pl.Datetime("us", "UTC"),
}


# ── Universe membership contract (schema stub may be empty initially) ───────

UNIVERSE_MEMBERSHIP_HISTORY_PK = [
    "universe_id",
    "instrument_id",
    "effective_from_date",
]
UNIVERSE_MEMBERSHIP_HISTORY = {
    "universe_id": pl.Utf8,
    "instrument_id": pl.Int64,
    "effective_from_date": pl.Date,
    "effective_to_date": pl.Date,
    "source": pl.Utf8,
    "membership_rule_version": pl.Utf8,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}


# ── Benchmark reference prices and calendar ──────────────────────────────────

BENCHMARK_PRICES_DAILY_PK = ["instrument_id", "source", "trade_date"]
BENCHMARK_PRICES_DAILY = {
    "instrument_id": pl.Int64,
    "source": pl.Utf8,
    "raw_source_symbol": pl.Utf8,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "adj_close": pl.Float64,
    "volume": pl.Float64,
    "currency": pl.Utf8,
    "ingested_at_utc": pl.Datetime("us", "UTC"),
}

TRADING_CALENDAR_PK = ["trade_date", "exchange"]
TRADING_CALENDAR = {
    "trade_date": pl.Date,
    "exchange": pl.Utf8,
    "is_trading_day": pl.Boolean,
    "market_open_utc": pl.Datetime("us", "UTC"),
    "market_close_utc": pl.Datetime("us", "UTC"),
    "is_early_close": pl.Boolean,
    "loaded_at": pl.Datetime("us", "UTC"),
}


# ── Deprecated compatibility schemas (temporary bridge only) ─────────────────

SECURITY_MASTER_PK = ["sid"]
SECURITY_MASTER = {
    "sid": pl.Utf8,
    "symbol_current": pl.Utf8,
    "symbol_vendor": pl.Utf8,
    "exchange": pl.Utf8,
    "asset_type": pl.Utf8,
    "country": pl.Utf8,
    "currency": pl.Utf8,
    "ipo_date": pl.Date,
    "delist_date": pl.Date,
    "is_active": pl.Boolean,
    "cik": pl.Utf8,
    "sector": pl.Utf8,
    "industry": pl.Utf8,
    "source_priority": pl.Int32,
    "first_seen_at": pl.Datetime("us", "UTC"),
    "last_seen_at": pl.Datetime("us", "UTC"),
    "valid_from": pl.Date,
    "valid_to": pl.Date,
}

SYMBOL_MAP_HISTORY_PK = ["sid", "effective_from"]
SYMBOL_MAP_HISTORY = {
    "sid": pl.Utf8,
    "symbol": pl.Utf8,
    "effective_from": pl.Date,
    "effective_to": pl.Date,
    "reason_code": pl.Utf8,
    "source": pl.Utf8,
}

PRICES_1D_UNADJUSTED_PK = ["sid", "trade_date"]
PRICES_1D_UNADJUSTED = {
    "sid": pl.Utf8,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "source_vendor": pl.Utf8,
    "source_symbol": pl.Utf8,
    "loaded_at": pl.Datetime("us", "UTC"),
}

PRICES_5M_UNADJUSTED_PK = ["sid", "ts_utc"]
PRICES_5M_UNADJUSTED = {
    "sid": pl.Utf8,
    "ts_utc": pl.Datetime("us", "UTC"),
    "ts_exchange": pl.Datetime("us"),
    "session_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "source_vendor": pl.Utf8,
    "loaded_at": pl.Datetime("us", "UTC"),
}

PRICES_30M_UNADJUSTED_PK = ["sid", "ts_utc"]
PRICES_30M_UNADJUSTED = {
    "sid": pl.Utf8,
    "ts_utc": pl.Datetime("us", "UTC"),
    "ts_exchange": pl.Datetime("us"),
    "session_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "source_vendor": pl.Utf8,
    "loaded_at": pl.Datetime("us", "UTC"),
}

PRICES_1D_SPLIT_ADJUSTED_PK = ["sid", "trade_date"]
PRICES_1D_SPLIT_ADJUSTED = {
    "sid": pl.Utf8,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "cum_split_factor": pl.Float64,
    "cum_total_return_factor": pl.Float64,
    "loaded_at": pl.Datetime("us", "UTC"),
}

FILINGS_PK = ["accession_no"]
FILINGS = {
    "sid": pl.Utf8,
    "cik": pl.Utf8,
    "accession_no": pl.Utf8,
    "form_type": pl.Utf8,
    "filed_at": pl.Date,
    "accepted_at": pl.Datetime("us", "UTC"),
    "period_end": pl.Date,
    "is_amendment": pl.Boolean,
    "source_url": pl.Utf8,
    "loaded_at": pl.Datetime("us", "UTC"),
}

FUNDAMENTALS_REPORTED_PK = ["accession_no", "metric_name", "period_end", "unit"]
FUNDAMENTALS_REPORTED = {
    "sid": pl.Utf8,
    "accession_no": pl.Utf8,
    "metric_name": pl.Utf8,
    "metric_value": pl.Float64,
    "unit": pl.Utf8,
    "statement_type": pl.Utf8,
    "period_start": pl.Date,
    "period_end": pl.Date,
    "fiscal_year": pl.Int32,
    "fiscal_quarter": pl.Int32,
    "accepted_at": pl.Datetime("us", "UTC"),
    "loaded_at": pl.Datetime("us", "UTC"),
}

FUNDAMENTALS_ASOF_DAILY_PK = ["sid", "trade_date", "metric_name"]
FUNDAMENTALS_ASOF_DAILY = {
    "sid": pl.Utf8,
    "trade_date": pl.Date,
    "metric_name": pl.Utf8,
    "metric_value": pl.Float64,
    "unit": pl.Utf8,
    "accession_no": pl.Utf8,
    "accepted_at": pl.Datetime("us", "UTC"),
    "loaded_at": pl.Datetime("us", "UTC"),
}

UNIVERSE_MEMBERSHIP_PK = ["trade_date", "sid", "universe_name"]
UNIVERSE_MEMBERSHIP = {
    "trade_date": pl.Date,
    "sid": pl.Utf8,
    "universe_name": pl.Utf8,
    "is_member": pl.Boolean,
    "is_primary_listing": pl.Boolean,
    "is_common_stock": pl.Boolean,
    "price_ok": pl.Boolean,
    "liquidity_ok": pl.Boolean,
    "age_ok": pl.Boolean,
    "status_ok": pl.Boolean,
    "eligibility_reason": pl.Utf8,
}


# ── Validation helpers ────────────────────────────────────────────────────────

def validate_schema(
    df: pl.DataFrame | pl.LazyFrame,
    expected: dict[str, pl.DataType],
    table_name: str,
) -> list[str]:
    """Return schema-violation messages (empty list means valid)."""
    schema = df.schema

    errors: list[str] = []
    for col, dtype in expected.items():
        if col not in schema:
            errors.append(f"[{table_name}] missing column: {col}")
        elif schema[col] != dtype:
            errors.append(
                f"[{table_name}] column {col}: expected {dtype}, got {schema[col]}"
            )
    return errors


def check_pk_uniqueness(
    df: pl.DataFrame | pl.LazyFrame,
    pk_cols: list[str],
    table_name: str,
) -> int:
    """Return duplicate primary-key row count (0 means valid)."""
    if isinstance(df, pl.LazyFrame):
        df = df.collect()
    return len(df) - len(df.unique(subset=pk_cols))
