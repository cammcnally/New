"""QA checks for silver price tables."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("qa.prices")


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    for table_name in ("prices_1d_split_adjusted", "prices_1d_unadjusted"):
        table_dir = silver_path(table_name, settings)
        if not table_dir.exists():
            warnings.append(f"{table_name} directory not found")
            continue

        df = read_parquet(table_dir).collect()
        prefix = table_name
        stats[f"{prefix}_rows"] = len(df)

        dup_count = len(df) - len(df.unique(subset=["sid", "trade_date"]))
        if dup_count > 0:
            errors.append(f"[{prefix}] {dup_count} duplicate (sid, trade_date) rows")
        stats[f"{prefix}_pk_dupes"] = dup_count

        bad_ohlc = df.filter(
            (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
            | (pl.col("low") > pl.col("high"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
        )
        if len(bad_ohlc) > 0:
            errors.append(
                f"[{prefix}] {len(bad_ohlc)} rows with invalid OHLC bounds"
            )
        stats[f"{prefix}_bad_ohlc"] = len(bad_ohlc)

        neg_vol = df.filter(pl.col("volume") < 0)
        if len(neg_vol) > 0:
            errors.append(f"[{prefix}] {len(neg_vol)} rows with negative volume")
        stats[f"{prefix}_neg_volume"] = len(neg_vol)

        sorted_df = df.sort(["sid", "trade_date"])
        non_mono = sorted_df.with_columns(
            pl.col("trade_date").shift(1).over("sid").alias("prev_date"),
        ).filter(
            pl.col("prev_date").is_not_null()
            & (pl.col("trade_date") <= pl.col("prev_date"))
        )
        if len(non_mono) > 0:
            errors.append(
                f"[{prefix}] {len(non_mono)} non-monotonic date entries"
            )
        stats[f"{prefix}_non_monotonic"] = len(non_mono)

        with_ret = sorted_df.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("sid") - 1)
            .abs()
            .alias("abs_return")
        ).filter(pl.col("abs_return").is_not_null() & (pl.col("abs_return") > 0.5))
        if len(with_ret) > 0:
            warnings.append(
                f"[{prefix}] {len(with_ret)} rows with |return| > 50%"
            )
        stats[f"{prefix}_abnormal_returns"] = len(with_ret)

        sid_counts = df.group_by("sid").agg(pl.len().alias("n"))
        total_dates = df["trade_date"].n_unique()
        if total_dates > 0:
            missing_pct = sid_counts.with_columns(
                ((1 - pl.col("n") / total_dates) * 100).alias("missing_pct")
            )
            high_missing = missing_pct.filter(pl.col("missing_pct") > 50)
            if len(high_missing) > 0:
                warnings.append(
                    f"[{prefix}] {len(high_missing)} sids with >50% missing bars"
                )
            stats[f"{prefix}_high_missing_sids"] = len(high_missing)

    log.info("qa_prices: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
