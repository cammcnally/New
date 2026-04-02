from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.paths import bronze_path, silver_path
from market_data.silver.build_instrument_classification_history import build

pytestmark = pytest.mark.ingestion


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _write_symbol_history(test_settings) -> None:
    sym = pl.DataFrame(
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
        sym,
        silver_path("instrument_symbol_history", test_settings) / "instrument_symbol_history.parquet",
    )


def test_build_instrument_classification_history_prefers_dei_sic(test_settings) -> None:
    _write_symbol_history(test_settings)
    submissions = pl.DataFrame(
        {
            "cik": ["0000000001"],
            "company_name": ["AAA Corp"],
            "ticker_primary": ["AAA"],
            "exchange_primary": ["NYSE"],
            "accession_no": ["0001-24-000001"],
            "form_type": ["10-K"],
            "filing_date": [date(2024, 1, 10)],
            "accepted_at": [_utc(2024, 1, 10, 16, 0)],
            "primary_document": ["a10k.htm"],
            "is_xbrl": [True],
            "sic": ["1311"],
            "source_vendor": ["sec"],
            "loaded_at": [_utc(2024, 1, 10, 16, 5)],
        }
    ).with_columns(
        pl.col("accepted_at").cast(pl.Datetime("us", "UTC")),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        submissions,
        bronze_path("sec_submissions", test_settings) / "submissions.parquet",
    )
    companyfacts = pl.DataFrame(
        {
            "cik": ["0000000001"],
            "taxonomy": ["dei"],
            "concept": ["EntityPrimarySicNumber"],
            "label": ["Primary SIC"],
            "unit": ["pure"],
            "value": [3571.0],
            "start_date": [None],
            "end_date": [None],
            "filed_date": [date(2024, 2, 15)],
            "accession_no": ["0001-24-000002"],
            "form_type": ["10-Q"],
            "fiscal_year": [2024],
            "fiscal_period": ["Q1"],
            "frame": [None],
            "source_vendor": ["sec"],
            "loaded_at": [_utc(2024, 2, 15, 17, 0)],
        }
    ).with_columns(
        pl.col("start_date").cast(pl.Date),
        pl.col("end_date").cast(pl.Date),
        pl.col("filed_date").cast(pl.Date),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
        pl.col("frame").cast(pl.Utf8),
    )
    write_parquet(
        companyfacts,
        bronze_path("sec_companyfacts", test_settings) / "facts.parquet",
    )

    result = build(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-12-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("instrument_classification_history", test_settings)).collect()
    assert result["rows"] == 2
    assert out["classification_system"].unique().to_list() == ["SEC_SIC_4"]
    assert out["industry_group_code"].to_list() == ["1311", "3571"]
    assert out["sector_code"].to_list() == ["XLE", "XLK"]
    assert out["effective_to_date"].to_list()[0] == date(2024, 2, 14)
    assert out["source"].to_list() == [
        "sec_submissions_header_sic",
        "sec_dei_entity_primary_sic",
    ]


def test_build_instrument_classification_history_falls_back_to_submissions_sic(
    test_settings,
) -> None:
    _write_symbol_history(test_settings)
    submissions = pl.DataFrame(
        {
            "cik": ["0000000001"],
            "company_name": ["AAA Corp"],
            "ticker_primary": ["AAA"],
            "exchange_primary": ["NYSE"],
            "accession_no": ["0001-24-000001"],
            "form_type": ["10-K"],
            "filing_date": [date(2024, 1, 10)],
            "accepted_at": [_utc(2024, 1, 10, 16, 0)],
            "primary_document": ["a10k.htm"],
            "is_xbrl": [True],
            "sic": ["1311"],
            "source_vendor": ["sec"],
            "loaded_at": [_utc(2024, 1, 10, 16, 5)],
        }
    ).with_columns(
        pl.col("accepted_at").cast(pl.Datetime("us", "UTC")),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(
        submissions,
        bronze_path("sec_submissions", test_settings) / "submissions.parquet",
    )

    result = build(
        settings=test_settings,
        start_date="2024-01-01",
        end_date="2024-12-31",
        full_refresh=True,
    )

    out = read_parquet(silver_path("instrument_classification_history", test_settings)).collect()
    assert result["rows"] == 1
    assert out["industry_group_code"].to_list() == ["1311"]
    assert out["sector_code"].to_list() == ["XLE"]
    assert out["source"].to_list() == ["sec_submissions_header_sic"]
