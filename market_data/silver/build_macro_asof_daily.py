"""Point-in-time daily macro: latest vintage known by trade date, then latest observation."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.calendars import trading_days
from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.macro_asof_daily")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    vin_path = silver_path("macro_observations_vintage", settings)

    if not vin_path.exists():
        log.warning("silver macro_observations_vintage not found: %s", vin_path)
        return {"rows": 0}

    df = read_parquet(vin_path).collect()

    if len(df) == 0:
        log.warning("macro_observations_vintage is empty")
        return {"rows": 0}

    sd, ed = parse_date(start_date), parse_date(end_date)
    days = trading_days(sd, ed)
    if not days:
        log.warning("no trading days in range")
        return {"rows": 0}

    vintage_windows = (
        df.select(
            [
                "series_id",
                "vintage_date",
                "available_from_ts_utc",
                "available_to_ts_utc",
            ]
        )
        .unique()
        .sort(["series_id", "available_from_ts_utc"])
    )

    cal = pl.DataFrame({"asof_date": days}).with_columns(
        (
            pl.col("asof_date").cast(pl.Datetime("us", "UTC"))
            + pl.duration(days=1)
            - pl.duration(microseconds=1)
        ).alias("asof_cutoff_ts_utc")
    )
    series_ids = df.select("series_id").unique()

    left = series_ids.join(cal, how="cross").sort(["series_id", "asof_cutoff_ts_utc"])

    step1 = left.join_asof(
        vintage_windows,
        left_on="asof_cutoff_ts_utc",
        right_on="available_from_ts_utc",
        by="series_id",
        strategy="backward",
    ).filter(
        pl.col("vintage_date").is_not_null()
        & (
            pl.col("available_to_ts_utc").is_null()
            | (pl.col("asof_cutoff_ts_utc") <= pl.col("available_to_ts_utc"))
        )
    )

    step2 = (
        df.join(
            step1.select(
                [
                    "series_id",
                    "asof_date",
                    "asof_cutoff_ts_utc",
                    "vintage_date",
                    "available_from_ts_utc",
                ]
            ),
            on=["series_id", "vintage_date"],
            how="inner",
        )
        .filter(pl.col("observation_date") <= pl.col("asof_date"))
        .sort(["series_id", "asof_date", "observation_date"])
        .group_by(["series_id", "asof_date"], maintain_order=True)
        .last()
    )

    built_at = utc_now()
    out = step2.select(
        [
            "series_id",
            "asof_date",
            "observation_date",
            "value",
            pl.col("vintage_date").alias("selected_vintage_date"),
            pl.col("available_from_ts_utc").alias("selected_available_from_ts_utc"),
        ]
    ).with_columns(
        pl.lit("macro_asof_latest_available_v1").alias("selection_rule_version"),
        pl.lit(built_at).cast(pl.Datetime("us", "UTC")).alias("built_at_utc"),
        pl.col("asof_date").dt.year().alias("year"),
    )
    out = validate_contract_df("macro_asof_daily", out)

    out_dir = silver_path("macro_asof_daily", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    written = write_parquet(out, out_dir, partition_by=["year"])
    log.info("silver macro_asof_daily: %d rows -> %s", written, out_dir)
    return {"rows": written}
