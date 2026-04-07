"""Generate read-only compatibility security_master from canonical instrument_master."""
from __future__ import annotations

from datetime import date

import polars as pl

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import bronze_path, silver_path
from market_data.common.schema_registry import SECURITY_MASTER
from market_data.common.settings import IngestionSettings

log = get_logger("silver.compat_security_master")

_FAR_FUTURE = date(9999, 12, 31)


def build(
    *,
    settings: IngestionSettings,
    start_date: str | None = None,
    end_date: str | None = None,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)
    im_path = silver_path("instrument_master", settings) / "instrument_master.parquet"
    tickers_path = bronze_path("sec_company_tickers", settings) / "company_tickers.parquet"
    if not im_path.exists():
        log.warning("instrument_master not found: %s", im_path)
        return {"rows": 0}

    im = read_parquet(im_path).collect()
    cik_map = None
    if tickers_path.exists():
        cik_map = (
            read_parquet(tickers_path)
            .select(
                pl.col("ticker").cast(pl.Utf8).str.to_uppercase().alias("ticker"),
                pl.col("cik").cast(pl.Utf8).str.strip_chars().str.zfill(10).alias("cik"),
            )
            .collect()
            .unique(subset=["ticker"], keep="first")
        )
    out = im.select(
        pl.col("instrument_id").cast(pl.Utf8).alias("sid"),
        pl.col("canonical_symbol").alias("symbol_current"),
        pl.col("canonical_symbol").alias("symbol_vendor"),
        pl.col("exchange"),
        pl.col("asset_type"),
        pl.col("primary_country").alias("country"),
        pl.col("currency"),
        pl.col("first_seen_date").alias("ipo_date"),
        pl.when(pl.col("is_active_current")).then(pl.lit(None).cast(pl.Date)).otherwise(pl.col("last_seen_date")).alias("delist_date"),
        pl.col("is_active_current").alias("is_active"),
        pl.col("canonical_symbol").cast(pl.Utf8).str.to_uppercase().alias("_ticker"),
        pl.lit(None).cast(pl.Utf8).alias("sector"),
        pl.lit(None).cast(pl.Utf8).alias("industry"),
        pl.col("source_priority"),
        pl.col("created_at_utc").alias("first_seen_at"),
        pl.col("updated_at_utc").alias("last_seen_at"),
        pl.col("first_seen_date").alias("valid_from"),
        pl.when(pl.col("is_active_current")).then(pl.lit(_FAR_FUTURE)).otherwise(pl.col("last_seen_date")).alias("valid_to"),
    )
    if cik_map is not None:
        out = out.join(cik_map, left_on="_ticker", right_on="ticker", how="left")
    else:
        out = out.with_columns(pl.lit(None).cast(pl.Utf8).alias("cik"))
    out = out.drop("_ticker")
    for col, dtype in SECURITY_MASTER.items():
        if out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(dtype))

    out_path = silver_path("security_master", settings) / "security_master.parquet"
    written = write_parquet(out, out_path)
    log.info("compat security_master: %d rows -> %s", written, out_path)
    return {"rows": written}
