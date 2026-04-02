"""Normalize Stooq daily bulk-extracted CSVs into typed bronze Parquet."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.stooq_daily")


def _parse_stooq_csv(path: Path) -> pl.DataFrame | None:
    """Parse a single Stooq daily TXT/CSV file."""
    try:
        df = pl.read_csv(
            path,
            has_header=True,
            infer_schema_length=1000,
            ignore_errors=True,
        )
    except Exception:
        log.warning("failed to parse: %s", path)
        return None

    col_map = {c: c.strip().strip("<>").lower() for c in df.columns}
    df = df.rename(col_map)

    _ALT_NAMES = {"dtyyyymmdd": "date", "per": "date", "vol": "volume", "ticker": "_ticker"}
    rename_alts = {k: v for k, v in _ALT_NAMES.items() if k in df.columns and v not in df.columns}
    if rename_alts:
        df = df.rename(rename_alts)

    required = {"date", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        log.debug("skipping %s: missing columns %s after normalization", path.name, missing)
        return None

    raw_stem = path.stem.upper()
    ticker = raw_stem.split(".")[0] if "." in raw_stem else raw_stem

    df = df.with_columns([
        pl.lit(ticker).alias("symbol"),
        pl.col("date").cast(pl.Utf8).str.strptime(pl.Date, "%Y%m%d", strict=False).alias("trade_date"),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64) if "volume" in df.columns else pl.lit(0.0).alias("volume"),
        pl.lit("stooq").alias("source_vendor"),
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
    raw_dir = raw_path("stooq", "daily", settings)
    out_dir = bronze_path("stooq_prices_1d", settings)

    if full_refresh and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    all_dfs: list[pl.DataFrame] = []
    file_count = 0

    for txt_file in sorted(raw_dir.rglob("*.txt")):
        df = _parse_stooq_csv(txt_file)
        if df is not None and len(df) > 0:
            all_dfs.append(df)
            file_count += 1

    if not all_dfs:
        log.warning("no stooq daily files found in %s", raw_dir)
        return {"rows": 0, "files": 0}

    combined = pl.concat(all_dfs)

    sd, ed = parse_date(start_date), parse_date(end_date)
    combined = combined.filter(
        (pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed)
    )

    combined = combined.with_columns(
        pl.col("trade_date").dt.year().alias("year")
    )

    rows = write_parquet(combined, out_dir, partition_by=["year"])
    log.info("bronze stooq_prices_1d: %d rows from %d files", rows, file_count)
    return {"rows": rows, "files": file_count}
