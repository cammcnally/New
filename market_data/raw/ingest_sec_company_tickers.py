"""Ingest SEC-maintained company_tickers bootstrap mapping."""
from __future__ import annotations

import json

from market_data.clients.sec_client import SecClient
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings

log = get_logger("raw.sec_company_tickers")


def ingest(*, settings: IngestionSettings) -> dict[str, object]:
    dest = raw_path("sec", "company_tickers", settings)
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / "company_tickers.json"

    with SecClient(settings.sec_user_agent) as client:
        data = client.fetch_company_tickers()

    out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    count = len(data.get("data", data))
    log.info("SEC company_tickers bootstrap: rows=%d -> %s", count, out_path)
    return {"rows": count, "path": str(out_path)}
