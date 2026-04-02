"""Build silver universe_membership from security master, prices, and universe rules."""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from market_data.common.calendars import trading_days
from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings, load_yaml_config

log = get_logger("silver.universe_membership")

# U.S. primary listing venues (normalized upper-case exchange names from vendors).
_PRIMARY_US_EXCHANGES = frozenset(
    {
        "NYSE",
        "NASDAQ",
        "AMEX",
        "NYSE ARCA",
        "NYSE MKT",
        "NYSE AMERICAN",
        "NASDAQ NMS",
        "NASDAQ GLOBAL SELECT",
        "NASDAQ GLOBAL MARKET",
        "NASDAQ CAPITAL MARKET",
        "BATS",
        "IEX",
        "IEXG",
    }
)


def _normalize_exchange(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _price_lookback_start(start: date) -> date:
    """Calendar buffer so ~20 NYSE sessions exist before *start*."""
    return start - timedelta(days=45)


def _eligibility_reason_expr() -> pl.Expr:
    """Human-readable exclusion reasons when ``is_member`` is false."""

    def _reason(s: dict) -> str:
        if s.get("is_member"):
            return ""
        parts: list[str] = []
        if not s.get("country_ok"):
            parts.append("country_not_us")
        if not s.get("is_primary_listing"):
            parts.append("not_primary_listing")
        if not s.get("is_common_stock"):
            parts.append("not_common_stock")
        if not s.get("price_ok"):
            parts.append("price_below_min")
        if not s.get("liquidity_ok"):
            parts.append("liquidity_below_min")
        if not s.get("age_ok"):
            parts.append("listing_too_young")
        if not s.get("status_ok"):
            parts.append("invalid_listing_status")
        return "; ".join(parts)

    return pl.struct(
        [
            "country_ok",
            "is_primary_listing",
            "is_common_stock",
            "price_ok",
            "liquidity_ok",
            "age_ok",
            "status_ok",
            "is_member",
        ]
    ).map_elements(_reason, return_dtype=pl.Utf8)


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = full_refresh

    sd = parse_date(start_date)
    ed = parse_date(end_date)
    sessions = trading_days(sd, ed, exchange="XNYS")

    master_path = silver_path("security_master", settings)
    if not master_path.exists():
        log.warning("security_master silver path missing: %s", master_path)
        return {"rows": 0}

    sec = read_parquet(master_path).collect()
    if len(sec) == 0:
        log.warning("security_master is empty")
        return {"rows": 0}

    cfg = load_yaml_config("universe.yaml", settings)
    universes = cfg.get("universes") or {}

    prices_path = silver_path("prices_1d_unadjusted", settings)
    price_start = _price_lookback_start(sd)
    if prices_path.exists():
        prices_lf = read_parquet(prices_path).filter(
            (pl.col("trade_date") >= price_start) & (pl.col("trade_date") <= ed)
        )
        price_stats = (
            prices_lf.sort(["sid", "trade_date"])
            .with_columns(
                pl.col("volume")
                .rolling_mean(window_size=20, min_samples=20)
                .over("sid")
                .alias("avg_volume_20d")
            )
            .select("sid", "trade_date", "close", "avg_volume_20d")
        )
        px = price_stats.collect()
    else:
        log.warning("prices_1d_unadjusted not found under %s; price/liquidity gates fail", prices_path)
        px = pl.DataFrame(
            schema={
                "sid": pl.Utf8,
                "trade_date": pl.Date,
                "close": pl.Float64,
                "avg_volume_20d": pl.Float64,
            }
        )

    dates_df = pl.DataFrame({"trade_date": sessions})
    grid = dates_df.join(sec, how="cross")

    out_frames: list[pl.DataFrame] = []

    for universe_name, spec in universes.items():
        filters = spec.get("filters")
        if not filters:
            log.info("skip universe %r (no filters block)", universe_name)
            continue

        min_price = float(filters.get("min_price", 1.0))
        min_vol = float(filters.get("min_avg_volume_20d", 0.0))
        min_age = int(filters.get("min_listing_age_days", 0))
        want_country = str(filters.get("country", "US")).upper()
        exclude_types = {str(x).strip().lower() for x in filters.get("exclude_types") or []}
        allowed_types = {str(x).strip().lower() for x in filters.get("asset_types") or ["common_stock"]}

        u = grid.clone()
        u = u.join(px, on=["sid", "trade_date"], how="left")

        exch_norm = pl.col("exchange").map_elements(_normalize_exchange, return_dtype=pl.Utf8)
        is_primary_listing = exch_norm.is_in(list(_PRIMARY_US_EXCHANGES))

        # Alpha Vantage listing uses asset_type "stock" for common equity; map "common_stock" config to "stock".
        at = pl.col("asset_type").str.strip_chars().str.to_lowercase()
        matches_allowed = pl.lit(False)
        if "common_stock" in allowed_types:
            matches_allowed = matches_allowed | (at == "stock")
        for t in allowed_types:
            if t != "common_stock":
                matches_allowed = matches_allowed | (at == t)
        is_excluded_type = at.is_in(list(exclude_types))
        is_common_stock = matches_allowed & ~is_excluded_type

        country_ok = pl.col("country").str.to_uppercase() == pl.lit(want_country)

        price_ok = pl.col("close").is_not_null() & (pl.col("close") >= min_price)
        liquidity_ok = pl.col("avg_volume_20d").is_not_null() & (pl.col("avg_volume_20d") >= min_vol)

        age_days = (pl.col("trade_date") - pl.col("ipo_date")).dt.total_days()
        age_ok = pl.col("ipo_date").is_not_null() & (age_days >= min_age)

        status_ok = (
            pl.when(pl.col("is_active"))
            .then(pl.lit(True))
            .when(pl.col("delist_date").is_not_null())
            .then(pl.col("trade_date") <= pl.col("delist_date"))
            .otherwise(pl.lit(False))
        )

        u = u.with_columns(
            is_primary_listing.alias("is_primary_listing"),
            is_common_stock.alias("is_common_stock"),
            country_ok.alias("country_ok"),
            price_ok.alias("price_ok"),
            liquidity_ok.alias("liquidity_ok"),
            age_ok.alias("age_ok"),
            status_ok.alias("status_ok"),
        )

        is_member = (
            pl.col("country_ok")
            & pl.col("is_primary_listing")
            & pl.col("is_common_stock")
            & pl.col("price_ok")
            & pl.col("liquidity_ok")
            & pl.col("age_ok")
            & pl.col("status_ok")
        )

        u = u.with_columns(
            is_member.alias("is_member"),
            pl.lit(universe_name).alias("universe_name"),
        )
        u = u.with_columns(_eligibility_reason_expr().alias("eligibility_reason"))

        u = u.select(
            [
                "trade_date",
                "sid",
                "universe_name",
                "is_member",
                "is_primary_listing",
                "is_common_stock",
                "price_ok",
                "liquidity_ok",
                "age_ok",
                "status_ok",
                "eligibility_reason",
            ]
        )
        u = u.with_columns(pl.col("trade_date").dt.year().alias("year"))
        out_frames.append(u)

    if not out_frames:
        log.warning("no filter-based universes produced rows")
        return {"rows": 0}

    out = pl.concat(out_frames)
    out_dir = silver_path("universe_membership", settings)
    written = write_parquet(out, out_dir, partition_by=["year"])
    log.info("silver universe_membership: %d rows -> %s", written, out_dir)
    return {"rows": written}
