from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.paths import bronze_path, silver_path
from market_data.silver.build_macro_asof_daily import build as build_macro_asof_daily
from market_data.silver.build_macro_observations_vintage import build as build_macro_observations_vintage

pytestmark = pytest.mark.ingestion


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_build_macro_observations_vintage_emits_canonical_columns(test_settings) -> None:
    bronze_dir = bronze_path("fred_vintages", test_settings)
    bronze_dir.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "vintage_date": [date(2024, 1, 10)],
            "realtime_start": [date(2024, 1, 10)],
            "realtime_end": [date(2099, 12, 31)],
            "loaded_at": [_utc(2024, 1, 10, 13, 0)],
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))
    write_parquet(df, bronze_dir, partition_by=["series_id"])

    build_macro_observations_vintage(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("macro_observations_vintage", test_settings)).collect()

    assert {
        "series_id",
        "observation_date",
        "value",
        "vintage_date",
        "release_ts_utc",
        "available_from_ts_utc",
        "available_to_ts_utc",
        "source",
        "ingested_at_utc",
    }.issubset(set(out.columns))


def test_build_macro_asof_daily_emits_canonical_selection_fields(test_settings) -> None:
    vintage_dir = silver_path("macro_observations_vintage", test_settings)
    vintage_dir.mkdir(parents=True, exist_ok=True)
    vintages = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL", "CPIAUCSL"],
            "observation_date": [date(2024, 1, 1), date(2024, 1, 1)],
            "value": [100.0, 101.0],
            "vintage_date": [date(2024, 1, 10), date(2024, 1, 20)],
            "release_ts_utc": [_utc(2024, 1, 10, 13, 0), _utc(2024, 1, 20, 13, 0)],
            "available_from_ts_utc": [_utc(2024, 1, 10, 13, 0), _utc(2024, 1, 20, 13, 0)],
            "available_to_ts_utc": [_utc(2024, 1, 20, 12, 59), None],
            "source": ["fred", "fred"],
            "ingested_at_utc": [_utc(2024, 1, 10, 13, 1), _utc(2024, 1, 20, 13, 1)],
        }
    ).with_columns(
        pl.col("release_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_to_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(vintages, vintage_dir, partition_by=["series_id"])

    build_macro_asof_daily(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-01-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("macro_asof_daily", test_settings)).collect()

    assert {
        "series_id",
        "asof_date",
        "observation_date",
        "value",
        "selected_vintage_date",
        "selected_available_from_ts_utc",
        "selection_rule_version",
        "built_at_utc",
    }.issubset(set(out.columns))
    assert out["selection_rule_version"].to_list() == ["macro_asof_latest_available_v1"] * len(out)
