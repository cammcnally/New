"""Normalize SEC company_tickers bootstrap into typed bronze parquet."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import bronze_path, raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.sec_company_tickers")


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str = "",
    end_date: str = "",
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date)
    raw_dir = raw_path("sec", "company_tickers", settings)
    in_path = raw_dir / "company_tickers.json"
    out_path = bronze_path("sec_company_tickers", settings) / "company_tickers.parquet"

    if full_refresh and out_path.exists():
        out_path.unlink()
    if not in_path.exists():
        log.warning("raw SEC company_tickers not found: %s", in_path)
        return {"rows": 0}

    data = json.loads(in_path.read_text(encoding="utf-8"))
    rows_obj = data.get("data", data)
    rows: list[dict[str, object]] = []
    if isinstance(rows_obj, dict):
        for value in rows_obj.values():
            if not isinstance(value, dict):
                continue
            rows.append(
                {
                    "ticker": value.get("ticker"),
                    "cik": value.get("cik_str"),
                    "company_name": value.get("title"),
                }
            )

    if not rows:
        log.warning("no company_tickers rows found")
        return {"rows": 0}

    df = (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("ticker").cast(pl.Utf8).str.strip_chars().str.to_uppercase(),
            pl.col("cik").cast(pl.Utf8).str.strip_chars().str.zfill(10),
            pl.col("company_name").cast(pl.Utf8).str.strip_chars(),
            pl.lit("sec").alias("source_vendor"),
            pl.lit(utc_now()).cast(pl.Datetime("us", "UTC")).alias("loaded_at"),
        )
        .unique(subset=["ticker"], keep="first")
        .sort("ticker")
    )

    written = write_parquet(df, out_path)
    log.info("bronze sec_company_tickers: %d rows -> %s", written, out_path)
    return {"rows": written}
