"""Alpha Vantage API client.

Used for:
  - listing status (active + delisted)
  - daily adjusted time series (splits, dividends)

NOT used as the primary bulk data backbone -- that role belongs to Stooq.
"""
from __future__ import annotations

import csv
import io
from typing import Any

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from market_data.common.dates import utc_now
from market_data.common.logging import get_logger
from market_data.common.rate_limiter import alpha_vantage_limiter


class AlphaVantageQuotaExhausted(Exception):
    """Raised when AV returns a rate-limit / premium-required message."""

log = get_logger("clients.alphavantage")

BASE_URL = "https://www.alphavantage.co/query"
_TIMEOUT = httpx.Timeout(30.0, read=60.0)


class AlphaVantageClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._limiter = alpha_vantage_limiter()
        self._client = httpx.Client(timeout=_TIMEOUT)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AlphaVantageClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=5, max=60),
        retry=retry_if_not_exception_type(AlphaVantageQuotaExhausted),
    )
    def _get(self, params: dict[str, str]) -> httpx.Response:
        self._limiter.wait()
        params["apikey"] = self._api_key
        resp = self._client.get(BASE_URL, params=params)
        resp.raise_for_status()
        text = resp.text
        if "Thank you for using Alpha Vantage" in text and "premium" in text.lower():
            raise AlphaVantageQuotaExhausted("Alpha Vantage quota exhausted -- wait or upgrade")
        return resp

    # ── Listing status ────────────────────────────────────────────────────

    def fetch_listing_status(self, state: str = "active") -> list[dict[str, str]]:
        """Fetch listing status CSV.  *state* is 'active' or 'delisted'."""
        log.info("fetching listing_status state=%s", state)
        resp = self._get({"function": "LISTING_STATUS", "state": state})
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        log.info("listing_status state=%s rows=%d", state, len(rows))
        return rows

    def fetch_all_listings(self) -> list[dict[str, Any]]:
        """Fetch both active and delisted listings."""
        active = self.fetch_listing_status("active")
        for r in active:
            r["_av_state"] = "active"

        delisted = self.fetch_listing_status("delisted")
        for r in delisted:
            r["_av_state"] = "delisted"

        combined = active + delisted
        log.info("all listings: %d active + %d delisted = %d total",
                 len(active), len(delisted), len(combined))
        return combined

    # ── Daily adjusted ────────────────────────────────────────────────────

    def fetch_daily_adjusted(
        self,
        symbol: str,
        outputsize: str = "full",
    ) -> dict[str, Any]:
        """Fetch TIME_SERIES_DAILY_ADJUSTED for a single symbol."""
        log.info("fetching daily_adjusted symbol=%s", symbol)
        resp = self._get({
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": outputsize,
        })
        data = resp.json()
        ts_key = "Time Series (Daily)"
        if ts_key not in data:
            log.warning("no daily data for %s: %s", symbol, list(data.keys()))
            return {"symbol": symbol, "records": [], "fetched_at": utc_now().isoformat()}

        records = []
        for date_str, bar in data[ts_key].items():
            records.append({
                "date": date_str,
                "open": float(bar["1. open"]),
                "high": float(bar["2. high"]),
                "low": float(bar["3. low"]),
                "close": float(bar["4. close"]),
                "adjusted_close": float(bar["5. adjusted close"]),
                "volume": int(float(bar["6. volume"])),
                "dividend_amount": float(bar["7. dividend amount"]),
                "split_coefficient": float(bar["8. split coefficient"]),
            })
        records.sort(key=lambda r: r["date"])
        log.info("daily_adjusted %s: %d bars", symbol, len(records))
        return {
            "symbol": symbol,
            "records": records,
            "fetched_at": utc_now().isoformat(),
        }
