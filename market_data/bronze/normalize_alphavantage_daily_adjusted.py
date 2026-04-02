"""Normalize Alpha Vantage daily adjusted JSON into typed bronze Parquet."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.av_daily_adjusted")


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("alphavantage", "daily_adjusted", settings)
    out_dir = bronze_path("av_daily_adjusted", settings)

    if full_refresh and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    all_rows: list[dict] = []

    for sym_dir in sorted(raw_dir.iterdir()):
        if not sym_dir.is_dir():
            continue
        json_files = sorted(sym_dir.glob("*.json"), reverse=True)
        if not json_files:
            continue

        data = json.loads(json_files[0].read_text())
        symbol = data.get("symbol", sym_dir.name)
        for rec in data.get("records", []):
            all_rows.append({
                "symbol": symbol,
                "trade_date": rec["date"],
                "open": rec["open"],
                "high": rec["high"],
                "low": rec["low"],
                "close": rec["close"],
                "adjusted_close": rec["adjusted_close"],
                "volume": float(rec["volume"]),
                "dividend_amount": rec["dividend_amount"],
                "split_coefficient": rec["split_coefficient"],
                "source_vendor": "alphavantage",
            })

    if not all_rows:
        log.warning("no AV daily adjusted data found")
        return {"rows": 0}

    df = pl.DataFrame(all_rows)
    df = df.with_columns([
        pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.lit(utc_now()).alias("loaded_at").cast(pl.Datetime("us", "UTC")),
    ])

    sd, ed = parse_date(start_date), parse_date(end_date)
    df = df.filter(
        (pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed)
    )

    df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
    rows = write_parquet(df, out_dir, partition_by=["year"])
    log.info("bronze av_daily_adjusted: %d rows", rows)
    return {"rows": rows}
