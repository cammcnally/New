"""Ingest daily OHLCV from Yahoo Finance for eligible instruments.

Scope rules:
- include common stocks and ETFs from Alpha Vantage listing status
- hard-include configured benchmark/reference instruments
- exclude rights, warrants, units, preferreds, and other explicit out-of-scope
  instruments with auditable logging
"""
from __future__ import annotations

import json
from pathlib import Path

from market_data.clients.yfinance_client import download_batch
from market_data.common.benchmarks import benchmark_symbols
from market_data.common.logging import get_logger
from market_data.common.paths import lake_root, raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.yfinance_daily")


def _is_excluded_listing(row: dict) -> tuple[bool, str | None]:
    """Return (exclude, reason) using explicit scope rules, not regex only."""
    symbol = str(row.get("symbol", "")).strip()
    name = str(row.get("name", "")).lower()
    asset_type = str(row.get("assetType", "")).strip().lower()

    if not symbol:
        return True, "empty_symbol"

    if symbol.startswith("$"):
        return True, "vendor_special_symbol"

    if any(token in name for token in ("warrant", "right", "rights", "unit", "units")):
        return True, "name_scope_exclusion"

    if any(token in name for token in ("preferred", "pref ", " preference")):
        return True, "preferred_share"

    if asset_type not in {"stock", "etf"}:
        return True, f"asset_type_{asset_type or 'unknown'}"

    return False, None


def _load_symbols(settings: IngestionSettings) -> tuple[list[str], list[dict[str, str]]]:
    """Load symbol list from AV listing status plus benchmark hard-includes."""
    listing_dir = raw_path("alphavantage", "listing_status", settings)
    if not listing_dir.exists():
        return [], []
    json_files = sorted(listing_dir.glob("*.json"), reverse=True)
    if not json_files:
        return [], []
    listings = json.loads(json_files[0].read_text())
    symbols: set[str] = set()
    exclusions: list[dict[str, str]] = []
    for r in listings:
        sym = str(r.get("symbol", "")).strip()
        exchange = str(r.get("exchange", "")).strip()
        if exchange not in ("NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "BATS"):
            exclusions.append({"symbol": sym, "reason": f"exchange_{exchange or 'unknown'}"})
            continue
        exclude, reason = _is_excluded_listing(r)
        if exclude:
            exclusions.append({"symbol": sym, "reason": reason or "excluded"})
            continue
        symbols.add(sym)

    for sym in benchmark_symbols(settings):
        symbols.add(sym)

    return sorted(symbols), exclusions


def ingest(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    dest = raw_path("yfinance", "daily", settings)
    exclusions_path = lake_root(settings) / "qa" / "symbol_exclusions.json"

    if full_refresh:
        import shutil
        if dest.exists():
            shutil.rmtree(dest)

    symbols, exclusions = _load_symbols(settings)
    if not symbols:
        log.error("no symbols found -- run AV listing ingest first")
        return {"method": "yfinance", "error": "no symbols"}

    exclusions_path.parent.mkdir(parents=True, exist_ok=True)
    exclusions_path.write_text(json.dumps(exclusions, indent=2))

    log.info(
        "yfinance daily ingest: %d symbols, %d exclusions, %s -> %s",
        len(symbols),
        len(exclusions),
        start_date,
        end_date,
    )
    result = download_batch(symbols, start_date, end_date, dest)
    result["method"] = "yfinance"
    result["requested_symbols"] = len(symbols)
    result["excluded_symbols"] = len(exclusions)
    result["exclusions_path"] = str(exclusions_path)
    return result
