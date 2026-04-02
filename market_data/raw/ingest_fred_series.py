"""Ingest FRED series observations (latest revision) for all configured series."""
from __future__ import annotations

import json

from market_data.clients.fred_client import FredClient
from market_data.common.dates import utc_now
from market_data.common.hashing import hash_bytes
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings, load_yaml_config

log = get_logger("raw.fred_series")


def ingest(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    dest = raw_path("fred", "observations", settings)
    dest.mkdir(parents=True, exist_ok=True)

    macro_config = load_yaml_config("macro_series.yaml", settings)
    series_list = macro_config.get("series", [])
    log.info("FRED series ingest: %d series", len(series_list))

    fetched = 0

    with FredClient(settings.fred_api_key) as client:
        for entry in series_list:
            sid = entry["id"]
            log.info("fetching FRED observations: %s", sid)
            try:
                obs = client.fetch_observations(sid, start_date=start_date, end_date=end_date)
                info = client.fetch_series_info(sid)

                payload = json.dumps({
                    "series_id": sid,
                    "series_info": info,
                    "observations": obs,
                    "fetched_at": utc_now().isoformat(),
                }, indent=2, default=str)

                content_hash = hash_bytes(payload.encode())[:16]
                out_path = dest / f"{sid}_{content_hash}.json"

                if not out_path.exists():
                    out_path.write_text(payload)
                    fetched += 1
                    log.info("saved %s: %d observations", sid, len(obs))
            except Exception:
                log.exception("failed FRED observations for %s", sid)

    log.info("FRED series ingest: fetched=%d", fetched)
    return {"fetched": fetched, "total_series": len(series_list)}
