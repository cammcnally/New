"""Ingest Alpha Vantage daily adjusted data for split/dividend reference.

This is NOT the primary price backbone (Stooq handles that).  AV daily
adjusted is used only for split coefficients and dividend amounts as a
reconciliation reference.  Rate limits make broad pulls impractical on
the free tier, so this ingestor works from a symbol list or the
benchmark/intraday-core universe.
"""
from __future__ import annotations

import json
from pathlib import Path

from market_data.clients.alphavantage_client import AlphaVantageClient
from market_data.common.benchmarks import benchmark_symbols
from market_data.common.dates import utc_now
from market_data.common.hashing import hash_bytes
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.av_daily_adjusted")


def _load_symbols(symbols_file: str | None, settings: IngestionSettings) -> list[str]:
    if symbols_file:
        return Path(symbols_file).read_text().strip().splitlines()

    return sorted(set(benchmark_symbols(settings)))


def ingest(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    symbols_file: str | None = None,
) -> dict[str, object]:
    dest = raw_path("alphavantage", "daily_adjusted", settings)
    dest.mkdir(parents=True, exist_ok=True)

    symbols = _load_symbols(symbols_file, settings)
    log.info("daily adjusted ingest: %d symbols", len(symbols))

    fetched = 0
    skipped = 0

    with AlphaVantageClient(settings.alpha_vantage_api_key) as client:
        for sym in symbols:
            sym_dir = dest / sym.upper()
            sym_dir.mkdir(parents=True, exist_ok=True)

            try:
                data = client.fetch_daily_adjusted(sym)
                payload = json.dumps(data, indent=2, default=str)
                content_hash = hash_bytes(payload.encode())[:16]
                out_path = sym_dir / f"{sym}_{content_hash}.json"

                if out_path.exists():
                    skipped += 1
                    continue

                out_path.write_text(payload)
                fetched += 1
            except Exception:
                log.exception("failed daily_adjusted for %s", sym)

    log.info("daily adjusted: fetched=%d skipped=%d total=%d", fetched, skipped, len(symbols))
    return {"fetched": fetched, "skipped": skipped, "total": len(symbols)}
