"""Ingest FRED/ALFRED vintage observations for revision-aware macro series."""
from __future__ import annotations

import json

from market_data.clients.fred_client import FredClient
from market_data.common.dates import utc_now
from market_data.common.hashing import hash_bytes
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path
from market_data.common.settings import IngestionSettings, load_yaml_config

log = get_logger("raw.fred_vintages")


def ingest(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    dest = raw_path("fred", "vintages", settings)
    dest.mkdir(parents=True, exist_ok=True)

    macro_config = load_yaml_config("macro_series.yaml", settings)
    series_list = [s for s in macro_config.get("series", []) if s.get("use_vintages", False)]
    log.info("FRED vintage ingest: %d series with vintages", len(series_list))

    fetched = 0

    with FredClient(settings.fred_api_key) as client:
        for entry in series_list:
            sid = entry["id"]
            series_dest = dest / sid
            series_dest.mkdir(parents=True, exist_ok=True)
            log.info("fetching FRED vintages: %s", sid)

            try:
                vintage_dates = client.fetch_vintage_dates(sid)
                vd_path = series_dest / "vintage_dates.json"
                vd_path.write_text(json.dumps({
                    "series_id": sid,
                    "vintage_dates": vintage_dates,
                    "fetched_at": utc_now().isoformat(),
                }, indent=2))

                for vd in vintage_dates:
                    vd_file = series_dest / f"vintage_{vd}.json"
                    if vd_file.exists():
                        continue

                    obs = client.fetch_vintage_observations(
                        sid, vd, start_date=start_date, end_date=end_date
                    )
                    payload = json.dumps({
                        "series_id": sid,
                        "vintage_date": vd,
                        "observations": obs,
                        "fetched_at": utc_now().isoformat(),
                    }, indent=2, default=str)

                    vd_file.write_text(payload)
                    fetched += 1

                log.info("vintages %s: %d total dates, fetched=%d new",
                         sid, len(vintage_dates), fetched)
            except Exception:
                log.exception("failed FRED vintages for %s", sid)

    log.info("FRED vintage ingest complete: fetched=%d", fetched)
    return {"fetched": fetched, "total_series": len(series_list)}
