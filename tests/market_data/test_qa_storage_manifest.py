from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.common.io_parquet import write_parquet
from market_data.common.manifest import build_manifest, write_manifest
from market_data.common.paths import manifest_dir, silver_path
from market_data.qa.qa_storage import check

pytestmark = pytest.mark.ingestion


def test_qa_storage_reads_dataset_manifest_row_counts(test_settings) -> None:
    security_master_dir = silver_path("security_master", test_settings)
    security_master_dir.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        {
            "sid": ["S1"],
            "symbol_current": ["AAA"],
            "symbol_vendor": ["AAA"],
            "exchange": ["NYSE"],
            "asset_type": ["stock"],
            "country": ["US"],
            "currency": ["USD"],
            "ipo_date": [date(2020, 1, 1)],
            "delist_date": [None],
            "is_active": [True],
            "cik": [None],
            "sector": [None],
            "industry": [None],
            "source_priority": [1],
            "first_seen_at": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "last_seen_at": [datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "valid_from": [date(2020, 1, 1)],
            "valid_to": [date(2099, 12, 31)],
        }
    ).with_columns(
        pl.col("delist_date").cast(pl.Date),
        pl.col("cik").cast(pl.Utf8),
        pl.col("sector").cast(pl.Utf8),
        pl.col("industry").cast(pl.Utf8),
        pl.col("source_priority").cast(pl.Int32),
        pl.col("first_seen_at").cast(pl.Datetime("us", "UTC")),
        pl.col("last_seen_at").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(df, security_master_dir / "security_master.parquet")

    dataset_manifest = build_manifest(
        datasets=[
            {
                "name": "security_master",
                "layer": "silver",
                "source_inputs": ["instrument_master"],
                "row_count": 1,
                "partitions": [],
                "content_hash": "abc",
            }
        ],
        run_id="dataset-build-1",
    )
    write_manifest(dataset_manifest, manifest_dir(test_settings) / "dataset_manifest.json")

    result = check(settings=test_settings)

    assert result["stats"]["silver/security_master_row_delta_pct"] == 0.0
