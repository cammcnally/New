from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.paths import silver_path
from market_data.silver.build_instrument_benchmark_map import build

pytestmark = pytest.mark.ingestion


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_build_instrument_benchmark_map_assigns_spy_and_optional_sector(test_settings) -> None:
    instrument_master = pl.DataFrame(
        {
            "instrument_id": [1, 2],
            "asset_type": ["equity", "equity"],
            "security_type": ["common_stock", "common_stock"],
            "canonical_symbol": ["AAA", "BBB"],
            "legal_name": ["AAA Corp", "BBB Corp"],
            "exchange": ["NYSE", "NYSE"],
            "primary_country": ["US", "US"],
            "currency": ["USD", "USD"],
            "is_active_current": [True, True],
            "first_seen_date": [date(2020, 1, 1), date(2020, 1, 1)],
            "last_seen_date": [date(2024, 1, 10), date(2024, 1, 10)],
            "source_priority": [1, 1],
            "created_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
            "updated_at_utc": [_utc(2024, 1, 1), _utc(2024, 1, 1)],
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

    classification_history = pl.DataFrame(
        {
            "instrument_id": [1],
            "classification_system": ["SEC_SIC_4"],
            "sector_code": ["XLK"],
            "sector_name": ["XLK"],
            "industry_group_code": ["3571"],
            "industry_group_name": ["3571"],
            "industry_code": [None],
            "industry_name": [None],
            "subindustry_code": [None],
            "subindustry_name": [None],
            "effective_from_date": [date(2024, 1, 1)],
            "effective_to_date": [None],
            "source": ["sec_dei_entity_primary_sic"],
            "ingested_at_utc": [_utc(2024, 2, 1)],
        }
    ).with_columns(
        pl.col("industry_code").cast(pl.Utf8),
        pl.col("industry_name").cast(pl.Utf8),
        pl.col("subindustry_code").cast(pl.Utf8),
        pl.col("subindustry_name").cast(pl.Utf8),
        pl.col("effective_to_date").cast(pl.Date),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        classification_history,
        silver_path("instrument_classification_history", test_settings)
        / "instrument_classification_history.parquet",
    )

    result = build(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-12-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("instrument_benchmark_map", test_settings)).collect().sort("instrument_id")
    assert result["rows"] == 2
    assert out["market_benchmark_id"].to_list() == ["bm_SPY", "bm_SPY"]
    assert out["sector_benchmark_id"].to_list() == ["bm_XLK", None]
    assert out["mapping_source"].to_list() == ["sec_sic4_crosswalk", "instrument_master_default_spy"]
