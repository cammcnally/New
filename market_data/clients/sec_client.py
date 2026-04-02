"""SEC EDGAR client for submissions and XBRL companyfacts.

Uses data.sec.gov JSON endpoints with fair-access pacing.
"""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from market_data.common.dates import utc_now
from market_data.common.logging import get_logger
from market_data.common.rate_limiter import sec_limiter

log = get_logger("clients.sec")

_TIMEOUT = httpx.Timeout(30.0, read=60.0)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class SecClient:
    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._limiter = sec_limiter()
        self._client = httpx.Client(
            timeout=_TIMEOUT,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SecClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def pad_cik(cik: str | int) -> str:
        """Zero-pad a CIK to 10 digits as required by SEC endpoints."""
        return str(cik).zfill(10)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15))
    def _get(self, url: str) -> dict[str, Any]:
        self._limiter.wait()
        resp = self._client.get(url)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    # ── Submissions ───────────────────────────────────────────────────────

    def fetch_submissions(self, cik: str | int) -> dict[str, Any]:
        """Fetch company submissions (recent + older filings)."""
        padded = self.pad_cik(cik)
        log.debug("fetching submissions CIK=%s", padded)
        url = SUBMISSIONS_URL.format(cik=padded)
        data = self._get(url)
        if not data:
            return {"cik": padded, "filings": [], "fetched_at": utc_now().isoformat()}

        recent = data.get("filings", {}).get("recent", {})
        filings = self._flatten_recent_filings(recent, padded)

        older_urls = [
            f["name"] for f in data.get("filings", {}).get("files", [])
        ]
        for older_file in older_urls:
            older_url = f"https://data.sec.gov/submissions/{older_file}"
            try:
                older_data = self._get(older_url)
                if older_data:
                    filings.extend(self._flatten_recent_filings(older_data, padded))
            except Exception:
                log.warning("failed to fetch older filings: %s", older_file)

        log.info("submissions CIK=%s: %d filings", padded, len(filings))
        return {
            "cik": padded,
            "name": data.get("name", ""),
            "sic": data.get("sic", ""),
            "tickers": data.get("tickers", []),
            "exchanges": data.get("exchanges", []),
            "filings": filings,
            "fetched_at": utc_now().isoformat(),
        }

    @staticmethod
    def _flatten_recent_filings(recent: dict, cik: str) -> list[dict[str, Any]]:
        if not recent:
            return []
        keys = list(recent.keys())
        if not keys:
            return []
        n = len(recent[keys[0]])
        rows: list[dict[str, Any]] = []
        for i in range(n):
            row = {k: recent[k][i] for k in keys}
            row["cik"] = cik
            rows.append(row)
        return rows

    # ── Company facts ─────────────────────────────────────────────────────

    def fetch_companyfacts(self, cik: str | int) -> dict[str, Any]:
        """Fetch XBRL company facts (all reported metrics)."""
        padded = self.pad_cik(cik)
        log.debug("fetching companyfacts CIK=%s", padded)
        url = COMPANYFACTS_URL.format(cik=padded)
        data = self._get(url)
        if not data:
            return {"cik": padded, "facts": {}, "fetched_at": utc_now().isoformat()}

        data["fetched_at"] = utc_now().isoformat()
        return data

    def fetch_company_tickers(self) -> dict[str, Any]:
        """Fetch SEC-maintained ticker to CIK bootstrap mapping."""
        log.debug("fetching SEC company_tickers bootstrap")
        data = self._get(COMPANY_TICKERS_URL)
        if not data:
            return {"fetched_at": utc_now().isoformat(), "data": {}}
        data["fetched_at"] = utc_now().isoformat()
        return data
