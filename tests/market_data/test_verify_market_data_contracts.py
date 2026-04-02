from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from market_data.common.io_parquet import write_parquet
from market_data.common.paths import silver_path
from market_data.common.pandera_contracts import ContractValidationError
from tools import verify_market_data_contracts as contracts_module

pytestmark = pytest.mark.ingestion

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_contract_verifier_fails_when_required_canonical_tables_are_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="missing required canonical tables"):
        contracts_module.run_checks(
            data_lake=str(tmp_path),
            config_dir=str(_CONFIG_DIR),
        )


def test_contract_verifier_allows_missing_deferred_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        contracts_module,
        "CONTRACT_PATHS",
        {
            "instrument_classification_history": "instrument_classification_history",
            "instrument_benchmark_map": "instrument_benchmark_map",
        },
    )

    assert contracts_module.run_checks(data_lake=str(tmp_path), config_dir=str(_CONFIG_DIR)) == 0


def test_contract_verifier_passes_with_minimal_required_tables(
    test_settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instrument_master = pl.DataFrame(
        {
            "instrument_id": [1],
            "asset_type": ["equity"],
            "security_type": ["common_stock"],
            "canonical_symbol": ["AAA"],
            "legal_name": ["AAA Corp"],
            "exchange": ["NYSE"],
            "primary_country": ["US"],
            "currency": ["USD"],
            "is_active_current": [True],
            "first_seen_date": [date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 1)],
            "source_priority": [1],
            "created_at_utc": [_utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 1)],
        }
    ).with_columns(
        pl.col("source_priority").cast(pl.Int32),
        pl.col("created_at_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("updated_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        instrument_master,
        silver_path("instrument_master", test_settings) / "instrument_master.parquet",
    )

    instrument_symbol_history = pl.DataFrame(
        {
            "instrument_id": [1],
            "source": ["alphavantage"],
            "raw_source_symbol": ["AAA"],
            "normalized_source_symbol": ["AAA"],
            "effective_from_date": [date(2020, 1, 1)],
            "effective_to_date": [None],
            "is_primary_for_source": [True],
            "ingested_at_utc": [_utc(2024, 1, 1)],
        }
    ).with_columns(
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        instrument_symbol_history,
        silver_path("instrument_symbol_history", test_settings) / "instrument_symbol_history.parquet",
    )

    prices = pl.DataFrame(
        {
            "sid": ["1"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "source_symbol": ["AAA"],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(
        prices,
        silver_path("prices_1d_unadjusted", test_settings) / "prices.parquet",
    )

    benchmark_definitions = pl.DataFrame(
        {
            "group": ["volatility", "volatility", "broad_market"],
            "symbol": ["^VIX", "VIXY", "SPY"],
            "benchmark_type": ["volatility_index", "volatility_etp", "market"],
            "semantic_role": [
                "canonical spot-volatility index reference",
                "tradable volatility ETP proxy",
                "default broad market benchmark",
            ],
            "default_usage": ["volatility_context", "tradable_vol_proxy", "default_market_benchmark"],
            "proxy_for": [None, "^VIX", None],
            "canonical_or_proxy": ["canonical", "proxy", "canonical"],
        }
    )
    write_parquet(
        benchmark_definitions,
        silver_path("benchmark_definitions", test_settings) / "benchmark_definitions.parquet",
    )

    trading_calendar = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 2)],
            "exchange": ["NYSE"],
            "is_trading_day": [True],
            "market_open_utc": [_utc(2024, 1, 2, 14, 30)],
            "market_close_utc": [_utc(2024, 1, 2, 21, 0)],
            "is_early_close": [False],
            "loaded_at": [_utc(2024, 1, 1)],
        }
    ).with_columns(
        pl.col("market_open_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("market_close_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        trading_calendar,
        silver_path("trading_calendar", test_settings) / "trading_calendar.parquet",
    )

    macro_vintages = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "vintage_date": [date(2024, 1, 10)],
            "release_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "available_from_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "available_to_ts_utc": [None],
            "source": ["fred"],
            "ingested_at_utc": [_utc(2024, 1, 10, 13, 1)],
        }
    ).with_columns(
        pl.col("release_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_to_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        macro_vintages,
        silver_path("macro_observations_vintage", test_settings) / "vintages.parquet",
    )

    macro_asof = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "asof_date": [date(2024, 1, 10)],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "selected_vintage_date": [date(2024, 1, 10)],
            "selected_available_from_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "selection_rule_version": ["macro_asof_latest_available_v1"],
            "built_at_utc": [_utc(2024, 1, 10, 13, 5)],
        }
    ).with_columns(
        pl.col("selected_available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("built_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        macro_asof,
        silver_path("macro_asof_daily", test_settings) / "asof.parquet",
    )

    assert (
        contracts_module.run_checks(
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "[contracts] checked=7" in out


def _minimal_price_row(sid: str = "1", trade_d: date | None = None) -> pl.DataFrame:
    d = trade_d or date(2024, 1, 2)
    return pl.DataFrame(
        {
            "sid": [sid],
            "trade_date": [d],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "source_symbol": ["AAA"],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))


def test_validate_silver_prices_partitioned_incremental(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    monkeypatch.setattr(contracts_module, "_INCREMENTAL_ROW_THRESHOLD", 0)
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    write_parquet(_minimal_price_row(trade_d=date(2023, 1, 3)), prices_dir / "y2023.parquet")
    write_parquet(_minimal_price_row(trade_d=date(2024, 1, 4)), prices_dir / "y2024.parquet")
    n = contracts_module.validate_silver_contract_dataset("prices_1d_unadjusted", prices_dir)
    assert n == 2


def test_validate_silver_prices_incremental_catches_cross_file_pk_dupes(
    monkeypatch: pytest.MonkeyPatch,
    test_settings,
) -> None:
    monkeypatch.setattr(contracts_module, "_INCREMENTAL_ROW_THRESHOLD", 0)
    prices_dir = silver_path("prices_1d_unadjusted", test_settings)
    prices_dir.mkdir(parents=True, exist_ok=True)
    row = _minimal_price_row()
    write_parquet(row, prices_dir / "a.parquet")
    write_parquet(row, prices_dir / "b.parquet")
    with pytest.raises(ContractValidationError, match="duplicate primary key"):
        contracts_module.validate_silver_contract_dataset("prices_1d_unadjusted", prices_dir)
