"""Normalize Stooq intraday (5-min) bulk-extracted CSVs into typed bronze Parquet."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.stooq_intraday")


def _parse_stooq_intraday_csv(path: Path) -> pl.DataFrame | None:
    try:
        df = pl.read_csv(path, has_header=True, infer_schema_length=1000, ignore_errors=True)
    except Exception:
        return None

    col_map = {c: c.strip().strip("<>").lower() for c in df.columns}
    df = df.rename(col_map)

    _ALT_NAMES = {"dtyyyymmdd": "date", "per": "date", "vol": "volume", "ticker": "_ticker"}
    rename_alts = {k: v for k, v in _ALT_NAMES.items() if k in df.columns and v not in df.columns}
    if rename_alts:
        df = df.rename(rename_alts)

    required = {"date", "time", "open", "high", "low", "close"}
    if not required.issubset(set(df.columns)):
        return None

    raw_stem = path.stem.upper()
    ticker = raw_stem.split(".")[0] if "." in raw_stem else raw_stem

    df = df.with_columns([
        pl.lit(ticker).alias("symbol"),
        (pl.col("date").cast(pl.Utf8) + " " + pl.col("time").cast(pl.Utf8))
            .str.strptime(pl.Datetime("us"), "%Y%m%d %H%M%S", strict=False)
            .alias("ts_exchange"),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64) if "volume" in df.columns else pl.lit(0.0).alias("volume"),
        pl.lit("stooq").alias("source_vendor"),
        pl.lit(utc_now()).alias("loaded_at"),
    ]).filter(pl.col("ts_exchange").is_not_null())

    df = df.with_columns([
        pl.col("ts_exchange").dt.replace_time_zone("America/New_York")
            .dt.convert_time_zone("UTC")
            .alias("ts_utc"),
        pl.col("ts_exchange").dt.date().alias("session_date"),
    ]).select([
        "symbol", "ts_utc", "ts_exchange", "session_date",
        "open", "high", "low", "close", "volume",
        "source_vendor", "loaded_at",
    ])

    return df


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("stooq", "intraday", settings)
    out_dir = bronze_path("stooq_prices_5m", settings)

    if full_refresh and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    all_dfs: list[pl.DataFrame] = []
    file_count = 0

    for txt_file in sorted(raw_dir.rglob("*.txt")):
        df = _parse_stooq_intraday_csv(txt_file)
        if df is not None and len(df) > 0:
            all_dfs.append(df)
            file_count += 1

    if not all_dfs:
        log.warning("no stooq intraday files found in %s", raw_dir)
        return {"rows": 0, "files": 0}

    combined = pl.concat(all_dfs)
    sd, ed = parse_date(start_date), parse_date(end_date)
    combined = combined.filter(
        (pl.col("session_date") >= sd) & (pl.col("session_date") <= ed)
    )

    combined = combined.with_columns([
        pl.col("session_date").dt.year().alias("year"),
        pl.col("session_date").dt.month().alias("month"),
    ])

    rows = write_parquet(combined, out_dir, partition_by=["year", "month"])
    log.info("bronze stooq_prices_5m: %d rows from %d files", rows, file_count)
    return {"rows": rows, "files": file_count}
