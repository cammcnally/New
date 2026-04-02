from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest

from market_data.silver.build_adjustment_factors import _factors_for_sid

pytestmark = pytest.mark.ingestion


def test_split_factor_chain() -> None:
    x_old = date(2024, 1, 2)
    x_new = date(2024, 6, 1)
    splits = pl.DataFrame(
        {
            "ex_date": [x_old, x_new],
            "split_coefficient": [2.0, 2.0],
        }
    )
    out = _factors_for_sid("SID", splits).sort("effective_date")
    assert out.filter(pl.col("effective_date") == x_old)["cum_split_factor"][0] == 0.5
    assert out.filter(pl.col("effective_date") == x_new)["cum_split_factor"][0] == 1.0

    x_only = date(2024, 3, 15)
    one = _factors_for_sid("SID2", pl.DataFrame({"ex_date": [x_only], "split_coefficient": [2.0]}))
    assert one["cum_split_factor"][0] == 1.0
    assert one["split_factor"][0] == 0.5


def test_price_adjustment() -> None:
    """Adjusted OHLC matches unadjusted * cum_split_factor (silver build_prices_1d_adjusted)."""
    x = date(2024, 4, 1)
    adj = pl.DataFrame(
        {
            "sid": ["S"] * 2,
            "effective_date": [date(2020, 1, 1), x],
            "cum_split_factor": [0.5, 1.0],
            "cum_total_return_factor": [0.5, 1.0],
        }
    )
    prices = pl.DataFrame(
        {
            "sid": ["S", "S"],
            "trade_date": [date(2024, 3, 15), date(2024, 4, 2)],
            "open": [100.0, 40.0],
            "high": [101.0, 41.0],
            "low": [99.0, 39.0],
            "close": [100.5, 40.5],
            "volume": [1_000_000.0, 2_000_000.0],
        }
    )
    loaded = datetime(2024, 4, 10, 0, 0, 0, tzinfo=timezone.utc)
    out = prices.join_asof(
        adj,
        left_on="trade_date",
        right_on="effective_date",
        by="sid",
        strategy="backward",
    ).with_columns(
        [
            pl.col("cum_split_factor").fill_null(1.0),
            pl.col("cum_total_return_factor").fill_null(1.0),
            pl.lit(loaded).cast(pl.Datetime("us", "UTC")).alias("loaded_at"),
        ]
    )
    f = pl.col("cum_split_factor")
    out = out.with_columns(
        [
            (pl.col("open") * f).alias("open_adj"),
            (pl.col("high") * f).alias("high_adj"),
            (pl.col("low") * f).alias("low_adj"),
            (pl.col("close") * f).alias("close_adj"),
            (pl.col("volume") / f).alias("volume_adj"),
        ]
    )
    assert out["open_adj"].to_list()[0] == 100.0 * 0.5
    assert out["close_adj"].to_list()[0] == 100.5 * 0.5
    assert out["volume_adj"].to_list()[0] == 1_000_000.0 / 0.5
    assert out["open_adj"].to_list()[1] == 40.0 * 1.0
