"""Ingest Alpha Vantage listing status (active + delisted)."""
from __future__ import annotations

import json

from market_data.clients.alphavantage_client import AlphaVantageClient
from market_data.common.dates import utc_now
from market_data.common.hashing import hash_bytes
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.av_listing")


def ingest(*, settings: IngestionSettings) -> dict[str, object]:
    dest = raw_path("alphavantage", "listing_status", settings)
    dest.mkdir(parents=True, exist_ok=True)

    with AlphaVantageClient(settings.alpha_vantage_api_key) as client:
        listings = client.fetch_all_listings()

    payload = json.dumps(listings, indent=2, default=str)
    content_hash = hash_bytes(payload.encode())[:16]
    out_path = dest / f"listing_status_{content_hash}.json"

    if out_path.exists():
        log.info("listing status already cached: %s", out_path.name)
    else:
        out_path.write_text(payload)
        log.info("saved listing status: %d records -> %s", len(listings), out_path.name)

    return {"rows": len(listings), "path": str(out_path)}
