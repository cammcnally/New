"""Ingest Stooq intraday (5-min, hourly) bulk ZIP archives."""
from __future__ import annotations

import json

from market_data.clients.stooq_client import (
    FIVE_MIN_US,
    HOURLY_US,
    build_raw_metadata,
    download_zip,
    extract_zip,
)
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.stooq_intraday")

URLS = {
    "5min": FIVE_MIN_US,
    "hourly": HOURLY_US,
}


def ingest(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    dest = raw_path("stooq", "intraday", settings)
    dest.mkdir(parents=True, exist_ok=True)

    results: dict[str, object] = {}

    for name, url in URLS.items():
        log.info("ingesting stooq intraday: %s", name)
        zip_path = download_zip(url, dest)
        extract_dir = dest / name
        if full_refresh and extract_dir.exists():
            import shutil
            shutil.rmtree(extract_dir)
        files = extract_zip(zip_path, extract_dir)

        meta = build_raw_metadata(url, zip_path)
        meta_path = dest / f"{name}_metadata.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        results[name] = {"zip": str(zip_path), "files": len(files)}

    log.info("stooq intraday ingest complete: %s", results)
    return results
