"""Point-in-time daily fundamentals: latest reported row known by each trade date."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.calendars import trading_days
from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.fundamentals_asof_daily")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    rep_path = silver_path("fundamentals_reported", settings)

    if not rep_path.exists():
        log.warning("silver fundamentals_reported not found: %s", rep_path)
        return {"rows": 0}

    fund = read_parquet(rep_path).collect()

    if len(fund) == 0:
        log.warning("fundamentals_reported is empty")
        return {"rows": 0}

    fund = fund.filter(pl.col("accepted_at").is_not_null())
    if len(fund) == 0:
        log.warning("no fundamentals rows with accepted_at")
        return {"rows": 0}

    fund = fund.sort("loaded_at").unique(
        subset=["sid", "metric_name", "accepted_at"],
        keep="last",
    )
    fund = fund.with_columns(pl.col("accepted_at").cast(pl.Datetime("us", "UTC")))

    sd, ed = parse_date(start_date), parse_date(end_date)
    days = trading_days(sd, ed)
    if not days:
        log.warning("no trading days in range")
        return {"rows": 0}

    cal = pl.DataFrame({"trade_date": days})
    keys = fund.select(["sid", "metric_name"]).unique()

    left = keys.join(cal, how="cross")
    left = left.with_columns(
        (
            pl.col("trade_date").cast(pl.Datetime("us", "UTC"))
            + pl.duration(days=1)
            - pl.duration(microseconds=1)
        ).alias("asof_ts"),
    ).sort(["sid", "metric_name", "asof_ts"])

    right = fund.sort(["sid", "metric_name", "accepted_at"])

    merged = left.join_asof(
        right,
        left_on="asof_ts",
        right_on="accepted_at",
        by=["sid", "metric_name"],
        strategy="backward",
    )

    loaded = utc_now()
    out = merged.select(
        [
            "sid",
            "trade_date",
            "metric_name",
            "metric_value",
            "unit",
            "accession_no",
            "accepted_at",
            pl.lit(loaded).cast(pl.Datetime("us", "UTC")).alias("loaded_at"),
        ]
    ).with_columns(pl.col("trade_date").dt.year().alias("year"))

    out_dir = silver_path("fundamentals_asof_daily", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    written = write_parquet(out, out_dir, partition_by=["year"])
    log.info("silver fundamentals_asof_daily: %d rows -> %s", written, out_dir)
    return {"rows": written}
