"""Promote bronze FRED vintage observations to silver with a stable column set."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import bronze_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.macro_observations_vintage")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date)

    in_dir = bronze_path("fred_vintages", settings)
    if not in_dir.exists():
        log.warning("bronze fred_vintages not found: %s", in_dir)
        return {"rows": 0}

    df = read_parquet(in_dir).collect()

    if len(df) == 0:
        log.warning("bronze fred_vintages is empty")
        return {"rows": 0}

    release_ts = pl.col("vintage_date").cast(pl.Datetime("us", "UTC"))
    loaded_ts = pl.col("loaded_at").cast(pl.Datetime("us", "UTC"))
    available_from_ts = pl.max_horizontal(release_ts, loaded_ts)
    available_to_ts = (
        pl.when(pl.col("realtime_end").is_null())
        .then(pl.lit(None).cast(pl.Datetime("us", "UTC")))
        .otherwise(
            pl.col("realtime_end").cast(pl.Datetime("us", "UTC"))
            + pl.duration(days=1)
            - pl.duration(microseconds=1)
        )
    )

    out = df.with_columns(
        release_ts.alias("release_ts_utc"),
        available_from_ts.alias("available_from_ts_utc"),
        available_to_ts.alias("available_to_ts_utc"),
        pl.lit("fred").alias("source"),
        loaded_ts.alias("ingested_at_utc"),
    ).select(
        [
            "series_id",
            "observation_date",
            "value",
            "vintage_date",
            "release_ts_utc",
            "available_from_ts_utc",
            "available_to_ts_utc",
            "source",
            "ingested_at_utc",
        ]
    )
    out = validate_contract_df("macro_observations_vintage", out)

    out_dir = silver_path("macro_observations_vintage", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    written = write_parquet(out, out_dir, partition_by=["series_id"])
    log.info("silver macro_observations_vintage: %d rows -> %s", written, out_dir)
    return {"rows": written}
