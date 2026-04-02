from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_data.common.benchmarks import derive_benchmark_id
from market_data.common.io_parquet import list_parquet_files, read_parquet, row_count
from market_data.common.pandera_contracts import (
    assert_lazy_primary_key_unique,
    contract_status,
    validate_contract_df,
    validate_contract_partition_local,
    validate_contract_schema_only,
    validate_non_overlapping_windows,
    table_primary_key_columns,
)
from market_data.common.paths import silver_path

try:
    from tools.verify_market_data_common import add_market_data_args, load_verification_settings
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_common import add_market_data_args, load_verification_settings


CONTRACT_PATHS = {
    "instrument_master": "instrument_master",
    "instrument_symbol_history": "instrument_symbol_history",
    "benchmark_definitions": "benchmark_definitions",
    "benchmark_prices_daily": "benchmark_prices_daily",
    "trading_calendar": "trading_calendar",
    "prices_1d_unadjusted": "prices_1d_unadjusted",
    "macro_observations_vintage": "macro_observations_vintage",
    "macro_asof_daily": "macro_asof_daily",
    "instrument_classification_history": "instrument_classification_history",
    "instrument_benchmark_map": "instrument_benchmark_map",
}

# Above this row count (or any multi-file layout), validate without a single full-table collect.
_INCREMENTAL_ROW_THRESHOLD = 750_000
_OPTIONAL_MISSING_CONTRACTS = {"macro_observations_vintage", "macro_asof_daily"}
# Enforced when materialized; absent directory is OK (see docs/data_contract.md benchmark OHLCV slice).
_VERIFIED_WHEN_PRESENT = frozenset({"benchmark_prices_daily"})


def _backfill_benchmark_definitions_benchmark_id_df(df: pl.DataFrame) -> pl.DataFrame:
    """Silver written before benchmark_id existed: derive stable ids from symbol."""
    if "benchmark_id" in df.columns:
        return df
    if "symbol" not in df.columns:
        return df
    return df.with_columns(
        pl.col("symbol")
        .map_elements(lambda s: derive_benchmark_id(str(s)), return_dtype=pl.Utf8)
        .alias("benchmark_id")
    )


def _backfill_benchmark_definitions_benchmark_id_lf(lf: pl.LazyFrame) -> pl.LazyFrame:
    if "benchmark_id" in lf.collect_schema().names():
        return lf
    if "symbol" not in lf.collect_schema().names():
        return lf
    return lf.with_columns(
        pl.col("symbol")
        .map_elements(lambda s: derive_benchmark_id(str(s)), return_dtype=pl.Utf8)
        .alias("benchmark_id")
    )


def _use_incremental_layout(path: Path) -> bool:
    files = list_parquet_files(path)
    if len(files) > 1:
        return True
    return row_count(path) > _INCREMENTAL_ROW_THRESHOLD


def _validate_full_collect(contract_name: str, path: Path) -> int:
    df = read_parquet(path).collect()
    if contract_name == "benchmark_definitions":
        df = _backfill_benchmark_definitions_benchmark_id_df(df)
    validate_contract_df(contract_name, df)
    return len(df)


def _validate_prices_incremental(path: Path) -> int:
    pk = table_primary_key_columns("prices_1d_unadjusted")
    for f in list_parquet_files(path):
        validate_contract_partition_local("prices_1d_unadjusted", pl.read_parquet(f))
    assert_lazy_primary_key_unique(
        read_parquet(path).select(pk), "prices_1d_unadjusted", pk
    )
    return row_count(path)


def _validate_macro_vintage_incremental(path: Path) -> int:
    pk = table_primary_key_columns("macro_observations_vintage")
    for f in list_parquet_files(path):
        validate_contract_partition_local("macro_observations_vintage", pl.read_parquet(f))
    assert_lazy_primary_key_unique(
        read_parquet(path).select(pk), "macro_observations_vintage", pk
    )
    return row_count(path)


def _validate_macro_asof_incremental(path: Path) -> int:
    pk = table_primary_key_columns("macro_asof_daily")
    for f in list_parquet_files(path):
        validate_contract_partition_local("macro_asof_daily", pl.read_parquet(f))
    assert_lazy_primary_key_unique(read_parquet(path).select(pk), "macro_asof_daily", pk)
    return row_count(path)


def _validate_trading_calendar_incremental(path: Path) -> int:
    pk = table_primary_key_columns("trading_calendar")
    for f in list_parquet_files(path):
        validate_contract_partition_local("trading_calendar", pl.read_parquet(f))
    assert_lazy_primary_key_unique(read_parquet(path).select(pk), "trading_calendar", pk)
    return row_count(path)


def _validate_instrument_master_incremental(path: Path) -> int:
    pk = table_primary_key_columns("instrument_master")
    for f in list_parquet_files(path):
        validate_contract_schema_only("instrument_master", pl.read_parquet(f))
    assert_lazy_primary_key_unique(read_parquet(path).select(pk), "instrument_master", pk)
    return row_count(path)


def _validate_benchmark_definitions_incremental(path: Path) -> int:
    pk = table_primary_key_columns("benchmark_definitions")
    for f in list_parquet_files(path):
        part = _backfill_benchmark_definitions_benchmark_id_df(pl.read_parquet(f))
        validate_contract_schema_only("benchmark_definitions", part)
    lf_pk = _backfill_benchmark_definitions_benchmark_id_lf(read_parquet(path))
    assert_lazy_primary_key_unique(lf_pk.select(pk), "benchmark_definitions", pk)
    df = _backfill_benchmark_definitions_benchmark_id_df(read_parquet(path).collect())
    validate_contract_df("benchmark_definitions", df)
    return len(df)


def _validate_benchmark_prices_daily_incremental(path: Path) -> int:
    pk = table_primary_key_columns("benchmark_prices_daily")
    for f in list_parquet_files(path):
        validate_contract_partition_local("benchmark_prices_daily", pl.read_parquet(f))
    assert_lazy_primary_key_unique(read_parquet(path).select(pk), "benchmark_prices_daily", pk)
    return row_count(path)


def _validate_instrument_symbol_history_incremental(path: Path) -> int:
    pk = table_primary_key_columns("instrument_symbol_history")
    for f in list_parquet_files(path):
        validate_contract_schema_only("instrument_symbol_history", pl.read_parquet(f))
    assert_lazy_primary_key_unique(
        read_parquet(path).select(pk), "instrument_symbol_history", pk
    )
    cols = [
        "instrument_id",
        "source",
        "normalized_source_symbol",
        "effective_from_date",
        "effective_to_date",
    ]
    df = read_parquet(path).select(cols).collect()
    validate_non_overlapping_windows(
        "instrument_symbol_history",
        df,
        group_cols=["instrument_id", "source", "normalized_source_symbol"],
        start_col="effective_from_date",
        end_col="effective_to_date",
    )
    return row_count(path)


def _validate_classification_incremental(path: Path) -> int:
    pk = table_primary_key_columns("instrument_classification_history")
    for f in list_parquet_files(path):
        validate_contract_schema_only("instrument_classification_history", pl.read_parquet(f))
    assert_lazy_primary_key_unique(
        read_parquet(path).select(pk), "instrument_classification_history", pk
    )
    cols = [
        "instrument_id",
        "classification_system",
        "effective_from_date",
        "effective_to_date",
    ]
    df = read_parquet(path).select(cols).collect()
    validate_non_overlapping_windows(
        "instrument_classification_history",
        df,
        group_cols=["instrument_id", "classification_system"],
        start_col="effective_from_date",
        end_col="effective_to_date",
    )
    return row_count(path)


def _validate_benchmark_map_incremental(path: Path) -> int:
    pk = table_primary_key_columns("instrument_benchmark_map")
    for f in list_parquet_files(path):
        validate_contract_schema_only("instrument_benchmark_map", pl.read_parquet(f))
    assert_lazy_primary_key_unique(
        read_parquet(path).select(pk), "instrument_benchmark_map", pk
    )
    cols = [
        "instrument_id",
        "market_benchmark_id",
        "sector_benchmark_id",
        "effective_from_date",
        "effective_to_date",
    ]
    df = read_parquet(path).select(cols).collect()
    validate_non_overlapping_windows(
        "instrument_benchmark_map",
        df,
        group_cols=["instrument_id"],
        start_col="effective_from_date",
        end_col="effective_to_date",
    )
    return row_count(path)


def validate_silver_contract_dataset(contract_name: str, path: Path) -> int:
    """Validate on-disk silver data for *contract_name*; return row count."""
    if not _use_incremental_layout(path):
        return _validate_full_collect(contract_name, path)
    dispatch: dict[str, object] = {
        "prices_1d_unadjusted": _validate_prices_incremental,
        "macro_observations_vintage": _validate_macro_vintage_incremental,
        "macro_asof_daily": _validate_macro_asof_incremental,
        "trading_calendar": _validate_trading_calendar_incremental,
        "instrument_master": _validate_instrument_master_incremental,
        "benchmark_definitions": _validate_benchmark_definitions_incremental,
        "benchmark_prices_daily": _validate_benchmark_prices_daily_incremental,
        "instrument_symbol_history": _validate_instrument_symbol_history_incremental,
        "instrument_classification_history": _validate_classification_incremental,
        "instrument_benchmark_map": _validate_benchmark_map_incremental,
    }
    fn = dispatch.get(contract_name)
    if fn is None:
        return _validate_full_collect(contract_name, path)
    return fn(path)  # type: ignore[operator]


def run_checks(*, data_lake: str | None = None, config_dir: str | None = None) -> int:
    args = argparse.Namespace(data_lake=data_lake, config_dir=config_dir)
    settings = load_verification_settings(args)

    checked = 0
    required_failures: list[str] = []
    skipped: list[str] = []
    for contract_name, dataset_name in CONTRACT_PATHS.items():
        status = contract_status(contract_name)
        required = (
            status != "contract_defined_deferred"
            and contract_name not in _OPTIONAL_MISSING_CONTRACTS
        )
        path = silver_path(dataset_name, settings)
        if not path.exists():
            if contract_name in _VERIFIED_WHEN_PRESENT:
                skipped.append(f"{contract_name}: missing (verified when present)")
                continue
            if required:
                required_failures.append(f"{contract_name}: missing")
            else:
                skipped.append(f"{contract_name}: missing")
            continue
        try:
            if row_count(path) == 0:
                if required:
                    required_failures.append(f"{contract_name}: empty")
                else:
                    skipped.append(f"{contract_name}: empty")
                continue
            n_rows = validate_silver_contract_dataset(contract_name, path)
        except Exception as exc:  # pragma: no cover - surfaced through exit status
            raise SystemExit(f"[contracts] failed to read or validate {contract_name}: {exc}") from exc
        print(f"[contracts] {contract_name} ({status}): ok ({n_rows} rows)")
        checked += 1

    if required_failures:
        raise SystemExit(f"[contracts] missing required canonical tables: {required_failures}")
    print(f"[contracts] checked={checked} skipped={len(skipped)}")
    for item in skipped:
        print(f"[contracts] skip {item}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate available market-data tables against Pandera contracts.")
    add_market_data_args(parser)
    args = parser.parse_args(argv)
    return run_checks(data_lake=args.data_lake, config_dir=args.config_dir)


if __name__ == "__main__":
    raise SystemExit(main())
