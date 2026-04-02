from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

pytestmark = pytest.mark.ingestion


def test_fundamentals_not_available_before_accepted() -> None:
    """Match silver build_fundamentals_asof_daily join_asof semantics."""
    accepted = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    fund = pl.DataFrame(
        {
            "sid": ["Z"],
            "metric_name": ["revenue"],
            "accepted_at": [accepted],
            "metric_value": [100.0],
            "unit": ["USD"],
            "accession_no": ["0001"],
        }
    ).with_columns(pl.col("accepted_at").cast(pl.Datetime("us", "UTC")))

    cal = pl.DataFrame(
        {"trade_date": [date(2024, 3, 14), date(2024, 3, 15)]}
    )
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

    mar14 = merged.filter(pl.col("trade_date") == date(2024, 3, 14))
    mar15 = merged.filter(pl.col("trade_date") == date(2024, 3, 15))

    assert mar14["metric_value"][0] is None
    assert mar15["metric_value"][0] == 100.0


def test_macro_vintage_selection() -> None:
    """Match silver build_macro_asof_daily vintage join + latest observation."""
    loaded = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    df = pl.DataFrame(
        {
            "series_id": ["SER"] * 4,
            "observation_date": [date(2024, 1, 5)] * 2 + [date(2024, 2, 5)] * 2,
            "value": [1.0, 1.1, 2.0, 2.1],
            "vintage_date": [date(2024, 1, 15)] * 2 + [date(2024, 2, 15)] * 2,
            "realtime_start": [date(2024, 1, 15)] * 4,
            "realtime_end": [date(2099, 12, 31)] * 4,
            "loaded_at": [loaded] * 4,
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))

    vintages = (
        df.select(["series_id", "vintage_date"])
        .unique()
        .sort(["series_id", "vintage_date"])
    )

    cal = pl.DataFrame({"trade_date": [date(2024, 1, 20), date(2024, 2, 20)]})
    series_ids = df.select("series_id").unique()

    left = series_ids.join(cal, how="cross").sort(["series_id", "trade_date"])

    step1 = left.join_asof(
        vintages,
        left_on="trade_date",
        right_on="vintage_date",
        by="series_id",
        strategy="backward",
    ).filter(pl.col("vintage_date").is_not_null())

    step2 = (
        df.join(step1, on=["series_id", "vintage_date"], how="inner")
        .filter(pl.col("observation_date") <= pl.col("trade_date"))
        .sort(["series_id", "trade_date", "observation_date"])
        .group_by(["series_id", "trade_date"], maintain_order=True)
        .last()
    )

    jan = step2.filter(pl.col("trade_date") == date(2024, 1, 20))
    feb = step2.filter(pl.col("trade_date") == date(2024, 2, 20))

    assert jan["vintage_date"][0] == date(2024, 1, 15)
    assert jan["value"][0] == 1.1
    assert feb["vintage_date"][0] == date(2024, 2, 15)
    assert feb["value"][0] == 2.1


def test_no_future_leakage() -> None:
    loaded = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    df = pl.DataFrame(
        {
            "series_id": ["SER"] * 3,
            "observation_date": [date(2024, 1, 5), date(2024, 1, 6), date(2024, 1, 7)],
            "value": [1.0, 2.0, 3.0],
            "vintage_date": [date(2024, 1, 10), date(2024, 1, 25), date(2024, 2, 1)],
            "realtime_start": [date(2024, 1, 1)] * 3,
            "realtime_end": [date(2099, 12, 31)] * 3,
            "loaded_at": [loaded] * 3,
        }
    ).with_columns(pl.col("loaded_at").cast(pl.Datetime("us", "UTC")))

    vintages = (
        df.select(["series_id", "vintage_date"])
        .unique()
        .sort(["series_id", "vintage_date"])
    )
    cal = pl.DataFrame({"trade_date": [date(2024, 1, 20)]})
    series_ids = df.select("series_id").unique()
    left = series_ids.join(cal, how="cross").sort(["series_id", "trade_date"])

    step1 = left.join_asof(
        vintages,
        left_on="trade_date",
        right_on="vintage_date",
        by="series_id",
        strategy="backward",
    ).filter(pl.col("vintage_date").is_not_null())

    step2 = (
        df.join(step1, on=["series_id", "vintage_date"], how="inner")
        .filter(pl.col("observation_date") <= pl.col("trade_date"))
        .sort(["series_id", "trade_date", "observation_date"])
        .group_by(["series_id", "trade_date"], maintain_order=True)
        .last()
    )

    assert step2.filter(pl.col("vintage_date") > pl.col("trade_date")).height == 0
