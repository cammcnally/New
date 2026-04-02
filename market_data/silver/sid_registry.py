"""Persistent monotonic SID registry.

sid_registry.parquet is a versioned canonical artifact. It maps
(exchange, symbol, listing_status, name) -> monotonic integer sid.

Existing assignments are authoritative. New symbols get appended IDs only.
Deleting the registry and rebuilding produces a valid but non-comparable
SID space -- this must be an explicit action.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.sid_registry")


def registry_path(settings: IngestionSettings) -> Path:
    return silver_path("sid_registry", settings) / "sid_registry.parquet"


def load_registry(settings: IngestionSettings) -> pl.DataFrame:
    p = registry_path(settings)
    if p.exists():
        return pl.read_parquet(p)
    return pl.DataFrame(schema={
        "sid": pl.Int64,
        "exchange": pl.Utf8,
        "symbol": pl.Utf8,
        "status": pl.Utf8,
        "name": pl.Utf8,
    })


def assign_sids(
    listings: pl.DataFrame,
    settings: IngestionSettings,
) -> pl.DataFrame:
    """Assign stable integer SIDs to listings.

    *listings* must have columns: exchange, symbol, status, name.
    Returns the same frame with an ``sid`` column (Int64) added.
    """
    registry = load_registry(settings)
    max_sid = registry["sid"].max() if len(registry) > 0 else 0
    if max_sid is None:
        max_sid = 0

    key_cols = ["exchange", "symbol", "status", "name"]
    new_listings = listings.select(key_cols).unique()

    if len(registry) > 0:
        already = registry.select(key_cols)
        new_only = new_listings.join(already, on=key_cols, how="anti")
    else:
        new_only = new_listings

    if len(new_only) > 0:
        new_only = new_only.sort(key_cols)
        new_only = new_only.with_columns(
            (pl.arange(0, pl.len(), eager=False) + max_sid + 1)
            .cast(pl.Int64)
            .alias("sid")
        )
        new_only = new_only.select(registry.columns)
        registry = pl.concat([registry, new_only])
        _save_registry(registry, settings)
        log.info("assigned %d new SIDs (total: %d)", len(new_only), len(registry))
    else:
        log.info("no new SIDs needed (total: %d)", len(registry))

    result = listings.join(
        registry.select("sid", *key_cols),
        on=key_cols,
        how="left",
    )
    return result


def _save_registry(registry: pl.DataFrame, settings: IngestionSettings) -> None:
    p = registry_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    registry.write_parquet(p)
    log.info("registry saved: %d entries -> %s", len(registry), p)
