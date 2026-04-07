from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.pandera_contracts import (
    CONTRACT_DEFINED_DEFERRED,
    ContractValidationError,
    validate_contract_df,
)

pytestmark = pytest.mark.ingestion


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _valid_instrument_master_df() -> pl.DataFrame:
    return pl.DataFrame(
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


def test_instrument_master_contract_accepts_valid_frame() -> None:
    validated = validate_contract_df("instrument_master", _valid_instrument_master_df())

    assert validated.height == 1


def test_instrument_master_contract_rejects_duplicate_pk() -> None:
    df = pl.concat([_valid_instrument_master_df(), _valid_instrument_master_df()])

    with pytest.raises(ContractValidationError, match="primary key"):
        validate_contract_df("instrument_master", df)


def test_instrument_master_contract_rejects_invalid_asset_type_enum() -> None:
    df = _valid_instrument_master_df().with_columns(pl.lit("crypto").alias("asset_type"))

    with pytest.raises(ContractValidationError, match="pandera validation failed"):
        validate_contract_df("instrument_master", df)


def test_instrument_symbol_history_contract_accepts_non_overlapping_windows() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1, 1],
            "source": ["alphavantage", "alphavantage"],
            "raw_source_symbol": ["AAA", "AAA"],
            "normalized_source_symbol": ["AAA", "AAA"],
            "effective_from_date": [date(2024, 1, 1), date(2024, 2, 1)],
            "effective_to_date": [date(2024, 1, 31), None],
            "is_primary_for_source": [True, True],
            "ingested_at_utc": [_utc(2024, 1, 1), _utc(2024, 2, 1)],
        }
    ).with_columns(
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )

    validated = validate_contract_df("instrument_symbol_history", df)

    assert validated.height == 2


def test_instrument_symbol_history_contract_rejects_overlapping_windows() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1, 1],
            "source": ["alphavantage", "alphavantage"],
            "raw_source_symbol": ["AAA", "AAA"],
            "normalized_source_symbol": ["AAA", "AAA"],
            "effective_from_date": [date(2024, 1, 1), date(2024, 1, 15)],
            "effective_to_date": [date(2024, 1, 31), date(2024, 2, 15)],
            "is_primary_for_source": [True, True],
            "ingested_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 15)],
        }
    ).with_columns(
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="overlap"):
        validate_contract_df("instrument_symbol_history", df)


def test_prices_contract_rejects_invalid_ohlc_bounds() -> None:
    df = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            "high": [9.0],
            "low": [8.0],
            "close": [10.0],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "source_symbol": ["AAA"],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="OHLC"):
        validate_contract_df("prices_1d_unadjusted", df)


def test_prices_contract_rejects_negative_volume() -> None:
    df = pl.DataFrame(
        {
            "sid": ["S1"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [-1.0],
            "source_vendor": ["yfinance"],
            "source_symbol": ["AAA"],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="negative volume"):
        validate_contract_df("prices_1d_unadjusted", df)


def test_macro_asof_daily_contract_rejects_future_available_timestamp() -> None:
    df = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "asof_date": [date(2024, 1, 10)],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "selected_vintage_date": [date(2024, 1, 10)],
            "selected_available_from_ts_utc": [_utc(2024, 1, 11, 0, 0)],
            "selection_rule_version": ["macro_asof_latest_available_v1"],
            "built_at_utc": [_utc(2024, 1, 11, 1, 0)],
        }
    ).with_columns(
        pl.col("selected_available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("built_at_utc").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="future-available"):
        validate_contract_df("macro_asof_daily", df)


def test_macro_observations_vintage_contract_rejects_release_after_available() -> None:
    df = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "vintage_date": [date(2024, 1, 10)],
            "release_ts_utc": [_utc(2024, 1, 10, 14, 0)],
            "available_from_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "available_to_ts_utc": [None],
            "source": ["fred"],
            "ingested_at_utc": [_utc(2024, 1, 10, 14, 1)],
        }
    ).with_columns(
        pl.col("release_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_to_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="release timestamp occurs after availability"):
        validate_contract_df("macro_observations_vintage", df)


def test_export_panel_contract_accepts_valid_frame() -> None:
    df = pl.DataFrame(
        {
            "ticker": ["AAA"],
            "timestamp_utc": [_utc(2024, 1, 2, 21, 0)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000.0],
            "is_incomplete_session": [False],
        }
    ).with_columns(
        pl.col("timestamp_utc").cast(pl.Datetime("us", "UTC")),
    )

    validated = validate_contract_df("export_panel", df)

    assert validated.shape == df.shape


def test_export_panel_contract_rejects_duplicate_keys() -> None:
    df = pl.DataFrame(
        {
            "ticker": ["AAA", "AAA"],
            "timestamp_utc": [_utc(2024, 1, 2, 21, 0), _utc(2024, 1, 2, 21, 0)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000.0, 1000.0],
            "is_incomplete_session": [False, False],
        }
    ).with_columns(
        pl.col("timestamp_utc").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="primary key"):
        validate_contract_df("export_panel", df)


def test_benchmark_definitions_contract_accepts_valid_catalog() -> None:
    from tests.market_data.benchmark_contract_fixtures import minimal_valid_benchmark_definitions_pl

    df = minimal_valid_benchmark_definitions_pl()

    validated = validate_contract_df("benchmark_definitions", df)

    assert validated.shape == df.shape


def test_benchmark_definitions_contract_rejects_invalid_vixy_mapping() -> None:
    from tests.market_data.benchmark_contract_fixtures import minimal_valid_benchmark_definitions_pl

    df = minimal_valid_benchmark_definitions_pl().with_columns(
        pl.when(pl.col("symbol") == "VIXY")
        .then(pl.lit("volatility_index"))
        .otherwise(pl.col("benchmark_type"))
        .alias("benchmark_type")
    )

    with pytest.raises(ContractValidationError, match="VIXY"):
        validate_contract_df("benchmark_definitions", df)


def test_trading_calendar_contract_accepts_open_and_closed_days() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 2), date(2024, 1, 6)],
            "exchange": ["NYSE", "NYSE"],
            "is_trading_day": [True, False],
            "market_open_utc": [_utc(2024, 1, 2, 14, 30), None],
            "market_close_utc": [_utc(2024, 1, 2, 21, 0), None],
            "is_early_close": [False, False],
            "loaded_at": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
        }
    ).with_columns(
        pl.col("market_open_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("market_close_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )

    validated = validate_contract_df("trading_calendar", df)

    assert validated.height == 2


def test_trading_calendar_contract_rejects_missing_session_timestamps_on_trading_day() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 2)],
            "exchange": ["NYSE"],
            "is_trading_day": [True],
            "market_open_utc": [None],
            "market_close_utc": [_utc(2024, 1, 2, 21, 0)],
            "is_early_close": [False],
            "loaded_at": [_utc(2024, 1, 1)],
        }
    ).with_columns(
        pl.col("market_open_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("market_close_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="trading days must carry both"):
        validate_contract_df("trading_calendar", df)


def test_instrument_classification_history_contract_rejects_overlapping_windows() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1, 1],
            "classification_system": ["gics", "gics"],
            "sector_code": ["10", "10"],
            "sector_name": ["Energy", "Energy"],
            "industry_group_code": ["1010", "1010"],
            "industry_group_name": ["Energy", "Energy"],
            "industry_code": ["101010", "101010"],
            "industry_name": ["Energy Equipment", "Energy Equipment"],
            "subindustry_code": ["10101010", "10101010"],
            "subindustry_name": ["Services", "Services"],
            "effective_from_date": [date(2024, 1, 1), date(2024, 1, 15)],
            "effective_to_date": [date(2024, 1, 31), None],
            "source": ["gics_vendor", "gics_vendor"],
            "ingested_at_utc": [_utc(2024, 1, 31), _utc(2024, 2, 1)],
        }
    ).with_columns(
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="overlap"):
        validate_contract_df("instrument_classification_history", df)


def test_instrument_classification_history_contract_accepts_sec_sic_4() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1],
            "classification_system": ["SEC_SIC_4"],
            "sector_code": ["1311"],
            "sector_name": ["Crude petroleum and natural gas"],
            "industry_group_code": [None],
            "industry_group_name": [None],
            "industry_code": [None],
            "industry_name": [None],
            "subindustry_code": [None],
            "subindustry_name": [None],
            "effective_from_date": [date(2024, 1, 1)],
            "effective_to_date": [None],
            "source": ["sec_edgar"],
            "ingested_at_utc": [_utc(2024, 1, 31)],
        }
    ).with_columns(
        pl.col("industry_group_code").cast(pl.Utf8),
        pl.col("industry_group_name").cast(pl.Utf8),
        pl.col("industry_code").cast(pl.Utf8),
        pl.col("industry_name").cast(pl.Utf8),
        pl.col("subindustry_code").cast(pl.Utf8),
        pl.col("subindustry_name").cast(pl.Utf8),
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    out = validate_contract_df("instrument_classification_history", df)
    assert out.height == 1


def test_instrument_benchmark_map_contract_rejects_overlapping_windows() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1, 1],
            "market_benchmark_id": ["bm_SPY", "bm_SPY"],
            "sector_benchmark_id": ["bm_XLK", "bm_XLK"],
            "effective_from_date": [date(2024, 1, 1), date(2024, 1, 15)],
            "effective_to_date": [date(2024, 1, 31), None],
            "mapping_rule_version": ["benchmark_map_v1", "benchmark_map_v1"],
            "mapping_source": ["sec_sic_crosswalk", "sec_sic_crosswalk"],
            "asof_timestamp": [_utc(2024, 1, 1), _utc(2024, 1, 15)],
        }
    ).with_columns(
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("sector_benchmark_id").cast(pl.Utf8),
        pl.col("asof_timestamp").cast(pl.Datetime("us", "UTC")),
    )

    with pytest.raises(ContractValidationError, match="overlap"):
        validate_contract_df("instrument_benchmark_map", df)


def test_deferred_contracts_are_registered() -> None:
    assert "instrument_classification_history" in CONTRACT_DEFINED_DEFERRED
    assert "instrument_benchmark_map" in CONTRACT_DEFINED_DEFERRED


def test_benchmark_prices_daily_silver_contract_accepts_valid_frame() -> None:
    df = pl.DataFrame(
        {
            "sid": ["1"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "source_vendor": ["yfinance"],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    out = validate_contract_df("benchmark_prices_daily", df)
    assert out.height == 1


def test_corporate_actions_silver_contract_accepts_valid_rows() -> None:
    df = pl.DataFrame(
        {
            "sid": ["S1", "S1"],
            "action_type": ["split", "dividend"],
            "ex_date": [date(2024, 1, 2), date(2024, 2, 1)],
            "cash_amount": [0.0, 0.5],
            "split_coefficient": [2.0, 1.0],
            "record_date": [None, None],
            "payment_date": [None, None],
            "declared_date": [None, None],
            "source_vendor": ["alphavantage", "alphavantage"],
            "loaded_at": [_utc(2024, 1, 3), _utc(2024, 2, 2)],
        }
    ).with_columns(
        pl.col("record_date").cast(pl.Date),
        pl.col("payment_date").cast(pl.Date),
        pl.col("declared_date").cast(pl.Date),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )
    out = validate_contract_df("corporate_actions", df)
    assert out.height == 2


def test_adjustment_factors_silver_contract_accepts_valid_rows() -> None:
    df = pl.DataFrame(
        {
            "sid": ["S1"],
            "effective_date": [date(2024, 1, 2)],
            "split_factor": [0.5],
            "dividend_factor": [1.0],
            "cum_split_factor": [1.0],
            "cum_total_return_factor": [1.0],
            "loaded_at": [_utc(2024, 1, 3)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    out = validate_contract_df("adjustment_factors", df)
    assert out.height == 1
