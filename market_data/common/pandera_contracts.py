from __future__ import annotations

from typing import Any, cast
from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping

import pandera.polars as pa
import polars as pl
from pandera.errors import SchemaError, SchemaErrors

from market_data.common.schema_registry import (
    BENCHMARK_DEFINITIONS,
    BENCHMARK_DEFINITIONS_PK,
    INSTRUMENT_BENCHMARK_MAP,
    INSTRUMENT_BENCHMARK_MAP_PK,
    INSTRUMENT_CLASSIFICATION_HISTORY,
    INSTRUMENT_CLASSIFICATION_HISTORY_PK,
    INSTRUMENT_MASTER,
    INSTRUMENT_MASTER_PK,
    INSTRUMENT_SYMBOL_HISTORY,
    INSTRUMENT_SYMBOL_HISTORY_PK,
    MACRO_ASOF_DAILY,
    MACRO_ASOF_DAILY_PK,
    MACRO_OBSERVATIONS_VINTAGE,
    MACRO_OBSERVATIONS_VINTAGE_PK,
    PRICES_1D_UNADJUSTED,
    PRICES_1D_UNADJUSTED_PK,
    TRADING_CALENDAR,
    TRADING_CALENDAR_PK,
)


ASSET_TYPE_VALUES = frozenset({"equity", "fund", "index", "unknown"})
SECURITY_TYPE_VALUES = frozenset({"common_stock", "etf", "etp_proxy", "index", "unknown"})
CLASSIFICATION_SYSTEM_VALUES = frozenset({"gics", "naics", "sic", "benchmark_group", "custom"})
BENCHMARK_TYPE_VALUES = frozenset(
    {
        "market",
        "duration",
        "credit",
        "sector",
        "volatility_index",
        "volatility_etp",
        "commodity",
        "commodity_etf",
        "custom",
    }
)
CANONICAL_OR_PROXY_VALUES = frozenset({"canonical", "proxy"})
MAPPING_TYPE_VALUES = frozenset(
    {
        "default_market_benchmark",
        "optional_alternate_benchmark",
        "broad_market",
        "sector",
        "duration",
        "credit",
        "volatility_context",
        "tradable_vol_proxy",
        "macro_context",
        "custom",
    }
)

CONTRACT_DEFINED_DEFERRED = frozenset(
    {
        "instrument_classification_history",
        "instrument_benchmark_map",
    }
)

_FAR_FUTURE = date(9999, 12, 31)


class ContractValidationError(ValueError):
    """Raised when a runtime data contract is violated."""


@dataclass(frozen=True)
class TableContract:
    name: str
    schema: pa.DataFrameSchema
    validators: tuple[Callable[[pl.DataFrame, str], None], ...]
    status: str


def _required_columns(
    spec: Mapping[str, object],
    *,
    nullable: set[str] | None = None,
    enum_checks: dict[str, tuple[str, ...] | frozenset[str]] | None = None,
) -> dict[str, pa.Column]:
    nullable = nullable or set()
    enum_checks = enum_checks or {}
    out: dict[str, pa.Column] = {}
    for col, dtype in spec.items():
        checks = []
        if col in enum_checks:
            checks.append(pa.Check.isin(list(enum_checks[col])))
        out[col] = pa.Column(
            cast(Any, dtype),
            nullable=col in nullable,
            checks=checks or None,
            required=True,
        )
    return out


def _ensure_pk_unique(df: pl.DataFrame, table_name: str, pk_cols: list[str]) -> None:
    dupes = len(df) - len(df.unique(subset=pk_cols))
    if dupes > 0:
        raise ContractValidationError(f"[{table_name}] duplicate primary key rows: {dupes}")


def _ensure_non_overlapping_windows(
    df: pl.DataFrame,
    table_name: str,
    *,
    group_cols: list[str],
    start_col: str,
    end_col: str,
) -> None:
    if df.is_empty():
        return

    sorted_df = df.sort(group_cols + [start_col]).with_columns(
        pl.col(end_col).fill_null(pl.lit(_FAR_FUTURE)).alias("__normalized_end"),
        pl.col(end_col)
        .fill_null(pl.lit(_FAR_FUTURE))
        .shift(1)
        .over(group_cols)
        .alias("__prev_end"),
    )
    overlaps = sorted_df.filter(
        pl.col("__prev_end").is_not_null() & (pl.col(start_col) <= pl.col("__prev_end"))
    )
    if len(overlaps) > 0:
        raise ContractValidationError(
            f"[{table_name}] effective-window overlap detected: {len(overlaps)} rows"
        )


def _ensure_ohlc_sane(df: pl.DataFrame, table_name: str) -> None:
    bad = df.filter(
        (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("low") > pl.col("high"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
    )
    if len(bad) > 0:
        raise ContractValidationError(f"[{table_name}] invalid OHLC bounds: {len(bad)} rows")


def _ensure_non_negative_volume(df: pl.DataFrame, table_name: str) -> None:
    neg = df.filter(pl.col("volume") < 0)
    if len(neg) > 0:
        raise ContractValidationError(f"[{table_name}] negative volume: {len(neg)} rows")


def _ensure_asof_not_future_available(df: pl.DataFrame, table_name: str) -> None:
    cutoff = (
        pl.col("asof_date").cast(pl.Datetime("us", "UTC"))
        + pl.duration(days=1)
        - pl.duration(microseconds=1)
    )
    future = df.filter(pl.col("selected_available_from_ts_utc") > cutoff)
    if len(future) > 0:
        raise ContractValidationError(
            f"[{table_name}] future-available macro selection detected: {len(future)} rows"
        )


def _ensure_release_not_after_available(df: pl.DataFrame, table_name: str) -> None:
    bad = df.filter(pl.col("release_ts_utc") > pl.col("available_from_ts_utc"))
    if len(bad) > 0:
        raise ContractValidationError(
            f"[{table_name}] release timestamp occurs after availability: {len(bad)} rows"
        )


def _ensure_benchmark_roles(df: pl.DataFrame, table_name: str) -> None:
    vix = df.filter(pl.col("symbol") == "^VIX")
    if len(vix) != 1:
        raise ContractValidationError(f"[{table_name}] expected exactly one ^VIX benchmark row")
    if (
        vix.item(0, "benchmark_type") != "volatility_index"
        or vix.item(0, "canonical_or_proxy") != "canonical"
    ):
        raise ContractValidationError(
            f"[{table_name}] ^VIX must remain the canonical volatility_index benchmark"
        )

    vixy = df.filter(pl.col("symbol") == "VIXY")
    if len(vixy) != 1:
        raise ContractValidationError(f"[{table_name}] expected exactly one VIXY benchmark row")
    if (
        vixy.item(0, "benchmark_type") != "volatility_etp"
        or vixy.item(0, "canonical_or_proxy") != "proxy"
        or vixy.item(0, "proxy_for") != "^VIX"
    ):
        raise ContractValidationError(
            f"[{table_name}] VIXY must remain a proxy volatility_etp for ^VIX and never an equivalent canonical index"
        )
    if vixy.item(0, "symbol") == vixy.item(0, "proxy_for"):
        raise ContractValidationError(f"[{table_name}] VIXY must not proxy to itself")


def _ensure_trading_calendar_sessions(df: pl.DataFrame, table_name: str) -> None:
    trading_rows_missing_sessions = df.filter(
        pl.col("is_trading_day")
        & (pl.col("market_open_utc").is_null() | pl.col("market_close_utc").is_null())
    )
    if len(trading_rows_missing_sessions) > 0:
        raise ContractValidationError(
            f"[{table_name}] trading days must carry both market_open_utc and market_close_utc"
        )

    closed_rows_with_sessions = df.filter(
        (~pl.col("is_trading_day"))
        & (pl.col("market_open_utc").is_not_null() | pl.col("market_close_utc").is_not_null())
    )
    if len(closed_rows_with_sessions) > 0:
        raise ContractValidationError(
            f"[{table_name}] non-trading days must not carry market session timestamps"
        )

    early_close_without_open = df.filter(pl.col("is_early_close") & (~pl.col("is_trading_day")))
    if len(early_close_without_open) > 0:
        raise ContractValidationError(
            f"[{table_name}] is_early_close may only be true on trading days"
        )


INSTRUMENT_MASTER_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        INSTRUMENT_MASTER,
        enum_checks={
            "asset_type": ASSET_TYPE_VALUES,
            "security_type": SECURITY_TYPE_VALUES,
        },
    ),
)

INSTRUMENT_SYMBOL_HISTORY_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        INSTRUMENT_SYMBOL_HISTORY,
        nullable={"effective_to_date"},
    ),
)

PRICES_1D_UNADJUSTED_SCHEMA = pa.DataFrameSchema(
    _required_columns(PRICES_1D_UNADJUSTED),
)

MACRO_OBSERVATIONS_VINTAGE_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        MACRO_OBSERVATIONS_VINTAGE,
        nullable={"available_to_ts_utc"},
    ),
)

MACRO_ASOF_DAILY_SCHEMA = pa.DataFrameSchema(
    _required_columns(MACRO_ASOF_DAILY),
)

INSTRUMENT_CLASSIFICATION_HISTORY_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        INSTRUMENT_CLASSIFICATION_HISTORY,
        nullable={
            "sector_code",
            "sector_name",
            "industry_group_code",
            "industry_group_name",
            "industry_code",
            "industry_name",
            "subindustry_code",
            "subindustry_name",
            "effective_to_date",
        },
        enum_checks={"classification_system": CLASSIFICATION_SYSTEM_VALUES},
    ),
)

INSTRUMENT_BENCHMARK_MAP_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        INSTRUMENT_BENCHMARK_MAP,
        nullable={"classification_system", "effective_to_date"},
        enum_checks={"mapping_type": MAPPING_TYPE_VALUES},
    ),
)

BENCHMARK_DEFINITIONS_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        BENCHMARK_DEFINITIONS,
        nullable={"proxy_for"},
        enum_checks={
            "benchmark_type": BENCHMARK_TYPE_VALUES,
            "canonical_or_proxy": CANONICAL_OR_PROXY_VALUES,
        },
    ),
)

TRADING_CALENDAR_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        TRADING_CALENDAR,
        nullable={"market_open_utc", "market_close_utc"},
    )
)

EXPORT_PANEL_SCHEMA = pa.DataFrameSchema(
    {
        "ticker": pa.Column(pl.Utf8),
        "timestamp_utc": pa.Column(pl.Datetime("us", "UTC")),
        "open": pa.Column(pl.Float64),
        "high": pa.Column(pl.Float64),
        "low": pa.Column(pl.Float64),
        "close": pa.Column(pl.Float64),
        "volume": pa.Column(pl.Float64),
        "is_incomplete_session": pa.Column(pl.Boolean),
    }
)


CONTRACTS: dict[str, TableContract] = {
    "instrument_master": TableContract(
        name="instrument_master",
        schema=INSTRUMENT_MASTER_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, INSTRUMENT_MASTER_PK),
        ),
        status="canonical_live",
    ),
    "instrument_symbol_history": TableContract(
        name="instrument_symbol_history",
        schema=INSTRUMENT_SYMBOL_HISTORY_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, INSTRUMENT_SYMBOL_HISTORY_PK),
            lambda df, table_name: _ensure_non_overlapping_windows(
                df,
                table_name,
                group_cols=["instrument_id", "source", "normalized_source_symbol"],
                start_col="effective_from_date",
                end_col="effective_to_date",
            ),
        ),
        status="canonical_live",
    ),
    "prices_1d_unadjusted": TableContract(
        name="prices_1d_unadjusted",
        schema=PRICES_1D_UNADJUSTED_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, PRICES_1D_UNADJUSTED_PK),
            _ensure_ohlc_sane,
            _ensure_non_negative_volume,
        ),
        status="canonical_live",
    ),
    "macro_observations_vintage": TableContract(
        name="macro_observations_vintage",
        schema=MACRO_OBSERVATIONS_VINTAGE_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, MACRO_OBSERVATIONS_VINTAGE_PK),
            _ensure_release_not_after_available,
        ),
        status="canonical_live",
    ),
    "macro_asof_daily": TableContract(
        name="macro_asof_daily",
        schema=MACRO_ASOF_DAILY_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, MACRO_ASOF_DAILY_PK),
            _ensure_asof_not_future_available,
        ),
        status="canonical_live",
    ),
    "instrument_classification_history": TableContract(
        name="instrument_classification_history",
        schema=INSTRUMENT_CLASSIFICATION_HISTORY_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(
                df, table_name, INSTRUMENT_CLASSIFICATION_HISTORY_PK
            ),
            lambda df, table_name: _ensure_non_overlapping_windows(
                df,
                table_name,
                group_cols=["instrument_id", "classification_system"],
                start_col="effective_from_date",
                end_col="effective_to_date",
            ),
        ),
        status="contract_defined_deferred",
    ),
    "instrument_benchmark_map": TableContract(
        name="instrument_benchmark_map",
        schema=INSTRUMENT_BENCHMARK_MAP_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(
                df, table_name, INSTRUMENT_BENCHMARK_MAP_PK
            ),
            lambda df, table_name: _ensure_non_overlapping_windows(
                df,
                table_name,
                group_cols=["instrument_id", "mapping_type", "benchmark_instrument_id"],
                start_col="effective_from_date",
                end_col="effective_to_date",
            ),
        ),
        status="contract_defined_deferred",
    ),
    "benchmark_definitions": TableContract(
        name="benchmark_definitions",
        schema=BENCHMARK_DEFINITIONS_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, BENCHMARK_DEFINITIONS_PK),
            _ensure_benchmark_roles,
        ),
        status="canonical_live",
    ),
    "trading_calendar": TableContract(
        name="trading_calendar",
        schema=TRADING_CALENDAR_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, TRADING_CALENDAR_PK),
            _ensure_trading_calendar_sessions,
        ),
        status="canonical_live",
    ),
    "export_panel": TableContract(
        name="export_panel",
        schema=EXPORT_PANEL_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(df, table_name, ["ticker", "timestamp_utc"]),
            _ensure_ohlc_sane,
            _ensure_non_negative_volume,
        ),
        status="compatibility_only",
    ),
}


def validate_contract_df(table_name: str, df: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    if isinstance(df, pl.LazyFrame):
        df = df.collect()

    contract = CONTRACTS.get(table_name)
    if contract is None:
        raise KeyError(f"Unknown market-data contract: {table_name}")

    try:
        validated = contract.schema.validate(df, lazy=True)
    except (SchemaError, SchemaErrors) as exc:
        raise ContractValidationError(f"[{table_name}] pandera validation failed: {exc}") from exc

    for validator in contract.validators:
        validator(validated, table_name)

    return validated


def contract_status(table_name: str) -> str:
    contract = CONTRACTS.get(table_name)
    if contract is None:
        raise KeyError(f"Unknown market-data contract: {table_name}")
    return contract.status
