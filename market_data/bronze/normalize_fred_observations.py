"""Normalize FRED series observations JSON into typed bronze Parquet."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.fred_observations")


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str = "",
    end_date: str = "",
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("fred", "observations", settings)
    out_path = bronze_path("fred_observations", settings) / "observations.parquet"

    if full_refresh and out_path.exists():
        out_path.unlink()

    all_rows: list[dict] = []

    for json_file in sorted(raw_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            log.warning("failed to parse: %s", json_file)
            continue

        series_id = data.get("series_id", "")
        for obs in data.get("observations", []):
            val = obs.get("value", ".")
            all_rows.append({
                "series_id": series_id,
                "observation_date": obs.get("date", ""),
                "value_raw": val,
                "realtime_start": obs.get("realtime_start", ""),
                "realtime_end": obs.get("realtime_end", ""),
                "source_vendor": "fred",
            })

    if not all_rows:
        log.warning("no FRED observation data found")
        return {"rows": 0}

    df = pl.DataFrame(all_rows)
    df = df.with_columns([
        pl.col("observation_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("realtime_start").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("realtime_end").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.when(pl.col("value_raw") == ".")
            .then(None)
            .otherwise(pl.col("value_raw").cast(pl.Float64, strict=False))
            .alias("value"),
        pl.lit(utc_now()).alias("loaded_at").cast(pl.Datetime("us", "UTC")),
    ]).drop("value_raw")

    rows = write_parquet(df, out_path)
    log.info("bronze fred_observations: %d rows", rows)
    return {"rows": rows}
