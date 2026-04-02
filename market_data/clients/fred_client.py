"""FRED / ALFRED API client for macro series and vintage-aware retrieval."""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from market_data.common.dates import utc_now
from market_data.common.logging import get_logger
from market_data.common.rate_limiter import fred_limiter

log = get_logger("clients.fred")

BASE_URL = "https://api.stlouisfed.org/fred"
_TIMEOUT = httpx.Timeout(30.0, read=60.0)


class FredClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._limiter = fred_limiter()
        self._client = httpx.Client(timeout=_TIMEOUT)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FredClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15))
    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        self._limiter.wait()
        params["api_key"] = self._api_key
        params["file_type"] = "json"
        url = f"{BASE_URL}{endpoint}"
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Series info ───────────────────────────────────────────────────────

    def fetch_series_info(self, series_id: str) -> dict[str, Any]:
        """Fetch series metadata."""
        data = self._get("/series", {"series_id": series_id})
        seriess = data.get("seriess", [])
        return seriess[0] if seriess else {}

    # ── Observations ──────────────────────────────────────────────────────

    def fetch_observations(
        self,
        series_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, str]]:
        """Fetch observation values for a series (latest revision)."""
        params: dict[str, str] = {"series_id": series_id}
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date

        all_obs: list[dict[str, str]] = []
        offset = 0
        limit = 10000

        while True:
            params["offset"] = str(offset)
            params["limit"] = str(limit)
            data = self._get("/series/observations", params)
            obs = data.get("observations", [])
            all_obs.extend(obs)
            if len(obs) < limit:
                break
            offset += limit

        log.info("observations %s: %d rows", series_id, len(all_obs))
        return all_obs

    # ── Vintage dates ─────────────────────────────────────────────────────

    def fetch_vintage_dates(self, series_id: str) -> list[str]:
        """Fetch all vintage dates for ALFRED revision history."""
        data = self._get("/series/vintagedates", {
            "series_id": series_id,
        })
        dates = data.get("vintage_dates", [])
        log.info("vintage_dates %s: %d vintages", series_id, len(dates))
        return dates

    # ── Vintage observations ──────────────────────────────────────────────

    def fetch_vintage_observations(
        self,
        series_id: str,
        vintage_date: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, str]]:
        """Fetch observations as of a specific vintage date (ALFRED)."""
        params: dict[str, str] = {
            "series_id": series_id,
            "realtime_start": vintage_date,
            "realtime_end": vintage_date,
        }
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date

        all_obs: list[dict[str, str]] = []
        offset = 0
        limit = 10000

        while True:
            params["offset"] = str(offset)
            params["limit"] = str(limit)
            data = self._get("/series/observations", params)
            obs = data.get("observations", [])
            all_obs.extend(obs)
            if len(obs) < limit:
                break
            offset += limit

        return all_obs

    def fetch_all_vintages(
        self,
        series_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all vintage observations for a series.

        Returns a flat list of dicts with ``observation_date``, ``value``,
        ``vintage_date``, ``realtime_start``, ``realtime_end``.
        """
        vintage_dates = self.fetch_vintage_dates(series_id)
        all_rows: list[dict[str, Any]] = []

        for vd in vintage_dates:
            obs = self.fetch_vintage_observations(
                series_id, vd, start_date=start_date, end_date=end_date
            )
            for o in obs:
                all_rows.append({
                    "series_id": series_id,
                    "observation_date": o.get("date", ""),
                    "value": o.get("value", ""),
                    "vintage_date": vd,
                    "realtime_start": o.get("realtime_start", vd),
                    "realtime_end": o.get("realtime_end", vd),
                    "fetched_at": utc_now().isoformat(),
                })

        log.info("all_vintages %s: %d rows across %d vintages",
                 series_id, len(all_rows), len(vintage_dates))
        return all_rows
