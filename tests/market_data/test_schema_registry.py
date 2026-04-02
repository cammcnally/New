from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.schema_registry import (
    SECURITY_MASTER,
    SECURITY_MASTER_PK,
    check_pk_uniqueness,
    validate_schema,
)

pytestmark = pytest.mark.ingestion


def _valid_security_master_row() -> pl.DataFrame:
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return pl.DataFrame(
        {
            "sid": ["S1"],
            "symbol_current": ["AAA"],
            "symbol_vendor": ["AAA"],
            "exchange": ["NYSE"],
            "asset_type": ["Stock"],
            "country": ["US"],
            "currency": ["USD"],
            "ipo_date": [date(2020, 1, 1)],
            "delist_date": [None],
            "is_active": [True],
            "cik": ["0001234567"],
            "sector": ["Tech"],
            "industry": ["Software"],
            "source_priority": [1],
            "first_seen_at": [base],
            "last_seen_at": [base],
            "valid_from": [date(2020, 1, 1)],
            "valid_to": [date(2099, 12, 31)],
        }
    ).with_columns(
        [
            pl.col("delist_date").cast(pl.Date),
            pl.col("first_seen_at").cast(pl.Datetime("us", "UTC")),
            pl.col("last_seen_at").cast(pl.Datetime("us", "UTC")),
            pl.col("source_priority").cast(pl.Int32),
        ]
    )


def test_validate_schema_valid() -> None:
    df = _valid_security_master_row()
    errs = validate_schema(df, SECURITY_MASTER, "security_master")
    assert errs == []


def test_validate_schema_missing_column() -> None:
    df = _valid_security_master_row().drop("cik")
    errs = validate_schema(df, SECURITY_MASTER, "security_master")
    assert any("missing column: cik" in e for e in errs)


def test_check_pk_uniqueness_no_dupes() -> None:
    df = pl.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "c"]})
    assert check_pk_uniqueness(df, ["id"], "t") == 0


def test_check_pk_uniqueness_with_dupes() -> None:
    df = pl.DataFrame({"id": [1, 1, 2], "v": ["a", "b", "c"]})
    assert check_pk_uniqueness(df, ["id"], "t") > 0
