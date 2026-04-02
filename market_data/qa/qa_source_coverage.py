"""Source-coverage audit over compatibility identity and price surfaces."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path, lake_root
from market_data.common.settings import IngestionSettings

log = get_logger("qa.source_coverage")


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    sm_path = silver_path("security_master", settings)
    px_path = silver_path("prices_1d_unadjusted", settings)

    if not sm_path.exists():
        return {
            "errors": ["generated compatibility security_master not found"],
            "warnings": [],
            "stats": {},
        }
    if not px_path.exists():
        return {"errors": ["prices_1d_unadjusted not found"], "warnings": [], "stats": {}}

    master = read_parquet(sm_path).select(
        "sid", "symbol_current", "exchange", "is_active", "delist_date"
    ).collect()

    prices = read_parquet(px_path).select("sid", "trade_date").collect()
    priced_sids = prices.select("sid").unique()
    price_date_range = prices.group_by("sid").agg(
        pl.col("trade_date").min().alias("first_bar"),
        pl.col("trade_date").max().alias("last_bar"),
        pl.len().alias("bar_count"),
    )

    listed_sids = master.select("sid").unique()
    stats["total_listed"] = len(listed_sids)
    stats["total_priced"] = len(priced_sids)

    matched = listed_sids.join(priced_sids, on="sid", how="inner")
    stats["matched"] = len(matched)
    stats["match_pct"] = round(len(matched) / max(len(listed_sids), 1) * 100, 1)

    listed_no_prices = listed_sids.join(priced_sids, on="sid", how="anti")
    listed_no_prices_syms = master.join(listed_no_prices, on="sid", how="inner").select(
        "sid", "symbol_current", "exchange"
    ).to_dicts()

    priced_no_listing = priced_sids.join(listed_sids, on="sid", how="anti")
    priced_no_listing_list = priced_no_listing["sid"].to_list()

    delisted = master.filter(~pl.col("is_active"))
    if len(delisted) > 0 and len(price_date_range) > 0:
        delisted_coverage = delisted.select("sid", "symbol_current", "delist_date").join(
            price_date_range, on="sid", how="left"
        ).filter(
            pl.col("last_bar").is_not_null()
            & pl.col("delist_date").is_not_null()
            & ((pl.col("delist_date").cast(pl.Date) - pl.col("last_bar")).dt.total_days() > 30)
        ).select("sid", "symbol_current", "delist_date", "last_bar").to_dicts()
    else:
        delisted_coverage = []

    if len(prices) > 0:
        max_dates = prices.group_by(pl.lit("all").alias("exchange")).agg(
            pl.col("trade_date").max().alias("max_bar_date")
        ).to_dicts()
        stats["max_bar_date"] = max_dates[0]["max_bar_date"].isoformat() if max_dates else None
    else:
        stats["max_bar_date"] = None

    if listed_no_prices_syms:
        warnings.append(f"{len(listed_no_prices_syms)} listed symbols have no price data")
    if priced_no_listing_list:
        warnings.append(f"{len(priced_no_listing_list)} priced SIDs have no listing match")
    if delisted_coverage:
        warnings.append(f"{len(delisted_coverage)} delisted symbols have broken coverage (>30 day gap)")

    result = {
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
        "listed_no_prices": listed_no_prices_syms[:100],
        "priced_no_listing": priced_no_listing_list[:100],
        "delisted_broken_coverage": delisted_coverage[:100],
    }

    out_path = lake_root(settings) / "qa" / "source_coverage.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    log.info("coverage audit: listed=%d priced=%d matched=%d (%.1f%%)",
             stats["total_listed"], stats["total_priced"], stats["matched"], stats["match_pct"])

    return result
