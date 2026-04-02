from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

pytestmark = pytest.mark.ingestion


def test_5m_to_30m_aggregation() -> None:
    """Match silver build_prices_30m_unadjusted resampling: 6 five-minute bars -> 1 thirty-minute bar."""
    tz = timezone.utc
    bars = [datetime(2024, 3, 1, 14, m, 0, tzinfo=tz) for m in range(0, 30, 5)]
    loaded = datetime(2024, 3, 1, 20, 0, 0, tzinfo=tz)

    df = pl.DataFrame(
        {
            "sid": ["QQQ"] * 6,
            "ts_utc": bars,
            "ts_exchange": bars,
            "session_date": [date(2024, 3, 1)] * 6,
            "open": [10.0, 11.0, 12.0, 11.5, 10.5, 10.0],
            "high": [10.5, 11.5, 13.0, 12.0, 11.0, 10.8],
            "low": [9.5, 10.5, 11.5, 11.0, 10.0, 9.8],
            "close": [10.2, 11.2, 12.5, 11.8, 10.3, 10.1],
            "volume": [100.0, 200.0, 300.0, 150.0, 250.0, 180.0],
            "source_vendor": ["stooq"] * 6,
            "loaded_at": [loaded] * 6,
        }
    ).with_columns(
        [
            pl.col("ts_utc").cast(pl.Datetime("us", "UTC")),
            pl.col("ts_exchange").cast(pl.Datetime("us")),
            pl.col("loaded_at").cast(pl.Datetime("us", "UTC")),
        ]
    )

    bucket = pl.col("ts_utc").dt.truncate("30m")
    agg = (
        df.with_columns(bucket.alias("ts_utc_bucket"))
        .group_by(["sid", "ts_utc_bucket"])
        .agg(
            [
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
            ]
        )
        .rename({"ts_utc_bucket": "ts_utc"})
    )

    assert agg.height == 1
    row = agg.row(0, named=True)
    assert row["open"] == 10.0
    assert row["high"] == 13.0
    assert row["low"] == 9.5
    assert row["close"] == 10.1
    assert row["volume"] == 1180.0
