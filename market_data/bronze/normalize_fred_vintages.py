"""Normalize FRED/ALFRED vintage observations into typed bronze Parquet."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.fred_vintages")


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str = "",
    end_date: str = "",
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("fred", "vintages", settings)
    out_dir = bronze_path("fred_vintages", settings)

    if full_refresh and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    all_rows: list[dict] = []

    for series_dir in sorted(raw_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        series_id = series_dir.name

        for vfile in sorted(series_dir.glob("vintage_*.json")):
            try:
                data = json.loads(vfile.read_text())
            except Exception:
                continue

            vintage_date = data.get("vintage_date", "")
            for obs in data.get("observations", []):
                val = obs.get("value", ".")
                all_rows.append({
                    "series_id": series_id,
                    "observation_date": obs.get("date", ""),
                    "value_raw": val,
                    "vintage_date": vintage_date,
                    "realtime_start": obs.get("realtime_start", vintage_date),
                    "realtime_end": obs.get("realtime_end", vintage_date),
                    "source_vendor": "fred",
                })

    if not all_rows:
        log.warning("no FRED vintage data found")
        return {"rows": 0}

    df = pl.DataFrame(all_rows)
    df = df.with_columns([
        pl.col("observation_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("vintage_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("realtime_start").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("realtime_end").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.when(pl.col("value_raw") == ".")
            .then(None)
            .otherwise(pl.col("value_raw").cast(pl.Float64, strict=False))
            .alias("value"),
        pl.lit(utc_now()).alias("loaded_at").cast(pl.Datetime("us", "UTC")),
    ]).drop("value_raw")

    df = df.with_columns(
        pl.col("series_id").alias("series_partition")
    )

    rows = write_parquet(df.drop("series_partition"), out_dir, partition_by=["series_id"])
    log.info("bronze fred_vintages: %d rows", rows)
    return {"rows": rows}
