"""Ingest SEC EDGAR submissions for all CIKs found in the security master.

Falls back to the listing-status raw data if the security master has not
been built yet.
"""
from __future__ import annotations

import json
from pathlib import Path

from market_data.clients.sec_client import SecClient
from market_data.common.dates import utc_now
from market_data.common.hashing import hash_bytes
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.sec_submissions")


def _load_ciks(settings: IngestionSettings) -> list[str]:
    """Collect CIKs from security master or raw AV listing status."""
    sm_path = silver_path("security_master", settings)
    if sm_path.exists():
        import polars as pl
        from market_data.common.io_parquet import read_parquet
        df = read_parquet(sm_path).select("cik").filter(pl.col("cik").is_not_null()).unique().collect()
        return df.get_column("cik").to_list()

    listing_dir = raw_path("alphavantage", "listing_status", settings)
    if listing_dir.exists():
        json_files = sorted(listing_dir.glob("*.json"), reverse=True)
        if json_files:
            listings = json.loads(json_files[0].read_text())
            return list({r.get("cik", "") for r in listings if r.get("cik")})

    log.warning("no CIK source found -- run listing_status ingest first")
    return []


def ingest(*, settings: IngestionSettings) -> dict[str, object]:
    dest = raw_path("sec", "submissions", settings)
    dest.mkdir(parents=True, exist_ok=True)

    ciks = _load_ciks(settings)
    log.info("SEC submissions ingest: %d CIKs", len(ciks))

    fetched = 0
    skipped = 0
    errors = 0

    with SecClient(settings.sec_user_agent) as client:
        for cik in ciks:
            padded = client.pad_cik(cik)
            out_path = dest / f"CIK{padded}.json"

            if out_path.exists():
                skipped += 1
                continue

            try:
                data = client.fetch_submissions(cik)
                if data.get("filings"):
                    payload = json.dumps(data, indent=2, default=str)
                    out_path.write_text(payload)
                    fetched += 1
                else:
                    skipped += 1
            except Exception:
                log.exception("failed submissions for CIK=%s", padded)
                errors += 1

    log.info("SEC submissions: fetched=%d skipped=%d errors=%d", fetched, skipped, errors)
    return {"fetched": fetched, "skipped": skipped, "errors": errors}
