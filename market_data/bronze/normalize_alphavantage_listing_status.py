"""Normalize Alpha Vantage listing status JSON into typed bronze Parquet."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.av_listing")


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str = "",
    end_date: str = "",
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("alphavantage", "listing_status", settings)
    out_path = bronze_path("av_listing_status", settings) / "listing_status.parquet"

    json_files = sorted(raw_dir.glob("*.json"), reverse=True)
    if not json_files:
        log.warning("no listing status raw files found")
        return {"rows": 0}

    records = json.loads(json_files[0].read_text())
    log.info("normalizing %d listing records from %s", len(records), json_files[0].name)

    rows = []
    for r in records:
        rows.append({
            "symbol": r.get("symbol", ""),
            "name": r.get("name", ""),
            "exchange": r.get("exchange", ""),
            "asset_type": r.get("assetType", ""),
            "ipo_date": r.get("ipoDate"),
            "delist_date": r.get("delistingDate"),
            "status": r.get("status", r.get("_av_state", "")),
            "source_vendor": "alphavantage",
            "loaded_at": utc_now(),
        })

    df = pl.DataFrame(rows)
    df = df.with_columns([
        pl.col("ipo_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("delist_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
    ])

    written = write_parquet(df, out_path)
    log.info("bronze av_listing_status: %d rows", written)
    return {"rows": written}
