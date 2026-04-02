"""Normalize Yahoo Finance daily CSVs into typed bronze Parquet."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.yfinance_daily")


def _parse_yfinance_csv(path: Path) -> pl.DataFrame | None:
    try:
        df = pl.read_csv(path, has_header=True, infer_schema_length=1000, ignore_errors=True)
    except Exception:
        return None

    col_map = {c: c.strip().lower() for c in df.columns}
    df = df.rename(col_map)

    date_col = "date" if "date" in df.columns else "price" if "price" in df.columns else None
    if date_col is None:
        return None

    required = {"open", "high", "low", "close"}
    if not required.issubset(set(df.columns)):
        return None

    ticker = path.stem.upper()

    volume_expr = (
        pl.col("volume").cast(pl.Float64)
        if "volume" in df.columns
        else pl.lit(0.0).alias("volume")
    )

    df = df.with_columns([
        pl.lit(ticker).alias("symbol"),
        pl.col(date_col).cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("trade_date"),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        volume_expr,
        pl.lit("yfinance").alias("source_vendor"),
        pl.lit(utc_now()).alias("loaded_at"),
    ]).select([
        "symbol", "trade_date", "open", "high", "low", "close", "volume",
        "source_vendor", "loaded_at",
    ]).filter(pl.col("trade_date").is_not_null())

    return df


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("yfinance", "daily", settings)
    out_dir = bronze_path("yfinance_prices_1d", settings)

    if full_refresh and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    if not raw_dir.exists():
        log.warning("no yfinance raw files found at %s", raw_dir)
        return {"rows": 0, "files": 0}

    all_dfs: list[pl.DataFrame] = []
    file_count = 0
    batch: list[pl.DataFrame] = []
    batch_threshold = 500

    for csv_file in sorted(raw_dir.glob("*.csv")):
        df = _parse_yfinance_csv(csv_file)
        if df is not None and len(df) > 0:
            batch.append(df)
            file_count += 1

        if len(batch) >= batch_threshold:
            all_dfs.append(pl.concat(batch))
            batch = []

    if batch:
        all_dfs.append(pl.concat(batch))

    if not all_dfs:
        log.warning("no yfinance daily files parsed from %s", raw_dir)
        return {"rows": 0, "files": 0}

    combined = pl.concat(all_dfs)
    sd, ed = parse_date(start_date), parse_date(end_date)
    combined = combined.filter(
        (pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed)
    )

    combined = combined.with_columns(pl.col("trade_date").dt.year().alias("year"))
    rows = write_parquet(combined, out_dir, partition_by=["year"])
    log.info("bronze yfinance_prices_1d: %d rows from %d files", rows, file_count)
    return {"rows": rows, "files": file_count}
