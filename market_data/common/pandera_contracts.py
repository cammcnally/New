from __future__ import annotations

from typing import Any, cast
from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping

import pandera.polars as pa
import polars as pl
from pandera.errors import SchemaError, SchemaErrors

from market_data.common.schema_registry import (
    ADJUSTMENT_FACTORS_SILVER_AV,
    ADJUSTMENT_FACTORS_SILVER_AV_PK,
    BENCHMARK_DEFINITIONS,
    BENCHMARK_DEFINITIONS_PK,
    BENCHMARK_PRICES_DAILY_SILVER,
    BENCHMARK_PRICES_DAILY_SILVER_PK,
    CORPORATE_ACTIONS_SILVER_AV,
    CORPORATE_ACTIONS_SILVER_AV_PK,
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
CLASSIFICATION_SYSTEM_VALUES = frozenset(
    {"gics", "naics", "sic", "benchmark_group", "custom", "SEC_SIC_4"}
)
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
CORPORATE_ACTION_TYPE_VALUES = frozenset({"split", "dividend"})

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


def _ensure_corporate_actions_silver_splits(df: pl.DataFrame, table_name: str) -> None:
    splits = df.filter(pl.col("action_type") == "split")
    bad = splits.filter(
        pl.col("split_coefficient").is_null() | (pl.col("split_coefficient") <= 0)
    )
    if len(bad) > 0:
        raise ContractValidationError(
            f"[{table_name}] split rows must have positive split_coefficient: {len(bad)} rows"
        )


def _ensure_corporate_actions_silver_dividends(df: pl.DataFrame, table_name: str) -> None:
    divs = df.filter(pl.col("action_type") == "dividend")
    bad = divs.filter(pl.col("cash_amount").is_not_null() & (pl.col("cash_amount") < 0))
    if len(bad) > 0:
        raise ContractValidationError(
            f"[{table_name}] dividend rows must not have negative cash_amount: {len(bad)} rows"
        )


def _ensure_adjustment_factors_silver_cumulative_positive(df: pl.DataFrame, table_name: str) -> None:
    bad = df.filter(
        (pl.col("cum_split_factor") <= 0) | (pl.col("cum_total_return_factor") <= 0)
    )
    if len(bad) > 0:
        raise ContractValidationError(
            f"[{table_name}] cumulative factors must be positive: {len(bad)} rows"
        )


_CANONICAL_SECTOR_ETF_SYMBOLS = frozenset(
    {"XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"}
)


def _ensure_benchmark_symbol_unique(df: pl.DataFrame, table_name: str) -> None:
    dup = df.group_by("symbol").len().filter(pl.col("len") > 1)
    if len(dup) > 0:
        raise ContractValidationError(f"[{table_name}] symbol column must be unique")


def _ensure_sole_primary_market_benchmark_is_spy(df: pl.DataFrame, table_name: str) -> None:
    prim = df.filter(pl.col("default_usage") == "default_market_benchmark")
    if prim.height != 1:
        raise ContractValidationError(
            f"[{table_name}] expected exactly one default_market_benchmark row, got {prim.height}"
        )
    if prim.item(0, "symbol") != "SPY":
        raise ContractValidationError(
            f"[{table_name}] default_market_benchmark must be SPY, got {prim.item(0, 'symbol')!r}"
        )


def _ensure_canonical_sector_benchmark_layer(df: pl.DataFrame, table_name: str) -> None:
    sector_rows = df.filter(pl.col("benchmark_type") == "sector")
    symbols = frozenset(sector_rows["symbol"].to_list())
    if symbols != _CANONICAL_SECTOR_ETF_SYMBOLS:
        raise ContractValidationError(
            f"[{table_name}] sector benchmarks must be exactly the 11 canonical "
            f"sector ETF symbols; got {sorted(symbols)}"
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
        nullable={"sector_benchmark_id", "effective_to_date"},
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

BENCHMARK_PRICES_DAILY_SILVER_SCHEMA = pa.DataFrameSchema(
    _required_columns(BENCHMARK_PRICES_DAILY_SILVER),
)

CORPORATE_ACTIONS_SILVER_AV_SCHEMA = pa.DataFrameSchema(
    _required_columns(
        CORPORATE_ACTIONS_SILVER_AV,
        nullable={"record_date", "payment_date", "declared_date"},
        enum_checks={"action_type": CORPORATE_ACTION_TYPE_VALUES},
    ),
)

ADJUSTMENT_FACTORS_SILVER_AV_SCHEMA = pa.DataFrameSchema(
    _required_columns(ADJUSTMENT_FACTORS_SILVER_AV),
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
                group_cols=["instrument_id"],
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
            _ensure_benchmark_symbol_unique,
            _ensure_sole_primary_market_benchmark_is_spy,
            _ensure_canonical_sector_benchmark_layer,
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
    "benchmark_prices_daily": TableContract(
        name="benchmark_prices_daily",
        schema=BENCHMARK_PRICES_DAILY_SILVER_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(
                df, table_name, list(BENCHMARK_PRICES_DAILY_SILVER_PK)
            ),
            _ensure_ohlc_sane,
            _ensure_non_negative_volume,
        ),
        status="canonical_live",
    ),
    "corporate_actions": TableContract(
        name="corporate_actions",
        schema=CORPORATE_ACTIONS_SILVER_AV_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(
                df, table_name, list(CORPORATE_ACTIONS_SILVER_AV_PK)
            ),
            _ensure_corporate_actions_silver_splits,
            _ensure_corporate_actions_silver_dividends,
        ),
        status="contract_defined_deferred",
    ),
    "adjustment_factors": TableContract(
        name="adjustment_factors",
        schema=ADJUSTMENT_FACTORS_SILVER_AV_SCHEMA,
        validators=(
            lambda df, table_name: _ensure_pk_unique(
                df, table_name, list(ADJUSTMENT_FACTORS_SILVER_AV_PK)
            ),
            _ensure_adjustment_factors_silver_cumulative_positive,
        ),
        status="contract_defined_deferred",
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


# Validators safe to run on each parquet partition/file independently (no cross-file PK/window).
_PARTITION_LOCAL_VALIDATORS: dict[str, tuple[Callable[[pl.DataFrame, str], None], ...]] = {
    "prices_1d_unadjusted": (_ensure_ohlc_sane, _ensure_non_negative_volume),
    "benchmark_prices_daily": (_ensure_ohlc_sane, _ensure_non_negative_volume),
    "macro_observations_vintage": (_ensure_release_not_after_available,),
    "macro_asof_daily": (_ensure_asof_not_future_available,),
    "trading_calendar": (_ensure_trading_calendar_sessions,),
}

_TABLE_PK_COLUMNS: dict[str, list[str]] = {
    "instrument_master": list(INSTRUMENT_MASTER_PK),
    "instrument_symbol_history": list(INSTRUMENT_SYMBOL_HISTORY_PK),
    "prices_1d_unadjusted": list(PRICES_1D_UNADJUSTED_PK),
    "macro_observations_vintage": list(MACRO_OBSERVATIONS_VINTAGE_PK),
    "macro_asof_daily": list(MACRO_ASOF_DAILY_PK),
    "instrument_classification_history": list(INSTRUMENT_CLASSIFICATION_HISTORY_PK),
    "instrument_benchmark_map": list(INSTRUMENT_BENCHMARK_MAP_PK),
    "benchmark_definitions": list(BENCHMARK_DEFINITIONS_PK),
    "benchmark_prices_daily": list(BENCHMARK_PRICES_DAILY_SILVER_PK),
    "trading_calendar": list(TRADING_CALENDAR_PK),
}


def validate_contract_schema_only(table_name: str, df: pl.DataFrame) -> pl.DataFrame:
    """Pandera schema only (no custom validators)."""
    contract = CONTRACTS.get(table_name)
    if contract is None:
        raise KeyError(f"Unknown market-data contract: {table_name}")
    try:
        validated = contract.schema.validate(df, lazy=True)
    except (SchemaError, SchemaErrors) as exc:
        raise ContractValidationError(f"[{table_name}] pandera validation failed: {exc}") from exc
    if isinstance(validated, pl.LazyFrame):
        validated = validated.collect()
    return validated


def validate_contract_partition_local(table_name: str, df: pl.DataFrame) -> None:
    """Schema plus validators that do not require cross-partition context."""
    validated = validate_contract_schema_only(table_name, df)
    for fn in _PARTITION_LOCAL_VALIDATORS.get(table_name, ()):
        fn(validated, table_name)


def assert_lazy_primary_key_unique(lf: pl.LazyFrame, table_name: str, pk_cols: list[str]) -> None:
    """Fail when duplicate PK rows exist (streaming-friendly; projects PK columns only)."""
    total = lf.select(pl.len()).collect().item()
    uniq = lf.unique(subset=pk_cols, keep="first").select(pl.len()).collect().item()
    dupes = total - uniq
    if dupes > 0:
        raise ContractValidationError(f"[{table_name}] duplicate primary key rows: {dupes}")


def validate_non_overlapping_windows(
    table_name: str,
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    start_col: str,
    end_col: str,
) -> None:
    """Run the canonical effective-window overlap check on a narrowed dataframe."""
    _ensure_non_overlapping_windows(
        df, table_name, group_cols=group_cols, start_col=start_col, end_col=end_col
    )


def validate_benchmark_definition_roles(df: pl.DataFrame) -> None:
    """Run ^VIX / VIXY role checks (expects a full benchmark_definitions frame)."""
    _ensure_benchmark_roles(df, "benchmark_definitions")


def table_primary_key_columns(table_name: str) -> list[str]:
    cols = _TABLE_PK_COLUMNS.get(table_name)
    if cols is None:
        raise KeyError(f"Unknown market-data contract: {table_name}")
    return cols
