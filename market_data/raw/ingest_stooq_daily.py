"""Ingest Stooq daily data for U.S. equities.

Strategy:
1. Try bulk ZIP download (fastest, 507 MB for all US)
2. If bulk fails (CAPTCHA, 404), fall back to per-ticker CSV downloads
   using the symbol list from AV listing status
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from market_data.clients.stooq_client import (
    DAILY_US_STOCKS,
    build_raw_metadata,
    download_ticker_csv,
    download_zip,
    extract_zip,
)
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.stooq_daily")


def _try_bulk_download(dest: Path) -> dict[str, object] | None:
    """Attempt bulk ZIP download. Returns result dict or None on failure."""
    try:
        zip_path = download_zip(DAILY_US_STOCKS, dest)
        extract_dir = dest / "us_stocks"
        files = extract_zip(zip_path, extract_dir)
        meta = build_raw_metadata(DAILY_US_STOCKS, zip_path)
        meta_path = dest / "us_stocks_metadata.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        log.info("bulk download succeeded: %d files extracted", len(files))
        return {"method": "bulk_zip", "files": len(files)}
    except Exception:
        log.warning("bulk ZIP download failed, will use per-ticker fallback")
        return None


def _load_symbols(settings: IngestionSettings) -> list[str]:
    """Load symbol list from AV listing status raw files."""
    listing_dir = raw_path("alphavantage", "listing_status", settings)
    if not listing_dir.exists():
        log.warning("no AV listing data found -- cannot determine symbols for per-ticker download")
        return []
    json_files = sorted(listing_dir.glob("*.json"), reverse=True)
    if not json_files:
        return []
    listings = json.loads(json_files[0].read_text())
    symbols = []
    for r in listings:
        sym = r.get("symbol", "")
        exchange = r.get("exchange", "")
        if sym and exchange in ("NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "BATS"):
            symbols.append(sym)
    return sorted(set(symbols))


def _per_ticker_download(
    dest: Path, symbols: list[str], start_date: str, end_date: str,
) -> dict[str, object]:
    """Download daily CSVs one ticker at a time."""
    ticker_dir = dest / "us_stocks"
    ticker_dir.mkdir(parents=True, exist_ok=True)

    sd = start_date.replace("-", "")
    ed = end_date.replace("-", "")
    fetched = 0
    skipped = 0
    errors = 0

    log.info("per-ticker download: %d symbols", len(symbols))
    for i, sym in enumerate(symbols):
        out_file = ticker_dir / f"{sym}.txt"
        if out_file.exists() and out_file.stat().st_size > 100:
            skipped += 1
            continue
        try:
            result = download_ticker_csv(sym, ticker_dir, start_date=sd, end_date=ed)
            if result:
                fetched += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
            log.debug("failed: %s", sym)

        if (i + 1) % 100 == 0:
            log.info("progress: %d/%d (fetched=%d skipped=%d errors=%d)",
                     i + 1, len(symbols), fetched, skipped, errors)
        time.sleep(0.3)

    log.info("per-ticker complete: fetched=%d skipped=%d errors=%d", fetched, skipped, errors)
    return {"method": "per_ticker", "fetched": fetched, "skipped": skipped, "errors": errors}


def ingest(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    dest = raw_path("stooq", "daily", settings)
    dest.mkdir(parents=True, exist_ok=True)

    if full_refresh:
        import shutil
        extract_dir = dest / "us_stocks"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

    result = _try_bulk_download(dest)
    if result is not None:
        return result

    symbols = _load_symbols(settings)
    if not symbols:
        log.error("no symbols available for per-ticker download")
        return {"method": "none", "error": "no symbols"}

    return _per_ticker_download(dest, symbols, start_date, end_date)
