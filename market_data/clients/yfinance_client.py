"""Yahoo Finance client for daily OHLCV data.

Fallback source when Stooq bulk downloads are unavailable.
Uses yfinance library which provides free, unauthenticated access
to Yahoo Finance historical data.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf  # type: ignore[import-untyped]

from market_data.common.dates import utc_now
from market_data.common.logging import get_logger

log = get_logger("clients.yfinance")


def download_batch(
    symbols: list[str],
    start_date: str,
    end_date: str,
    dest_dir: Path,
    batch_size: int = 50,
    pause_seconds: float = 1.0,
) -> dict[str, object]:
    """Download daily OHLCV for a batch of symbols.

    Saves one CSV per ticker in *dest_dir*. Skips tickers that already
    have a cached file unless the file is empty.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    fetched = 0
    skipped = 0
    no_data = 0
    errors = 0

    for batch_start in range(0, len(symbols), batch_size):
        batch = symbols[batch_start:batch_start + batch_size]
        download_threads = False
        to_fetch = []
        for sym in batch:
            out_file = dest_dir / f"{sym}.csv"
            if out_file.exists() and out_file.stat().st_size > 100:
                skipped += 1
                continue
            to_fetch.append(sym)

        if not to_fetch:
            continue

        log.info("downloading batch %d-%d (%d tickers to fetch)",
                 batch_start, batch_start + len(batch), len(to_fetch))

        try:
            log.info(
                "entering yf.download for batch %d-%d (threads=%s, start=%s, end=%s)",
                batch_start,
                batch_start + len(batch),
                download_threads,
                start_date,
                end_date,
            )
            data = yf.download(
                to_fetch,
                start=start_date,
                end=end_date,
                auto_adjust=False,
                group_by="ticker",
                threads=download_threads,
                progress=False,
            )
            log.info(
                "yf.download returned for batch %d-%d with shape=%s",
                batch_start,
                batch_start + len(batch),
                getattr(data, "shape", None),
            )

            if isinstance(data.columns, pd.MultiIndex):
                for sym in to_fetch:
                    try:
                        ticker_df = data[sym].dropna(how="all")
                        if len(ticker_df) == 0:
                            no_data += 1
                            continue
                        out_file = dest_dir / f"{sym}.csv"
                        ticker_df.to_csv(out_file)
                        fetched += 1
                    except (KeyError, Exception):
                        no_data += 1
            elif len(to_fetch) == 1:
                if len(data) > 0:
                    out_file = dest_dir / f"{to_fetch[0]}.csv"
                    data.to_csv(out_file)
                    fetched += 1
                else:
                    no_data += 1
        except Exception:
            log.exception("batch download failed at offset %d", batch_start)
            errors += len(to_fetch)

        if batch_start + batch_size < len(symbols):
            time.sleep(pause_seconds)

    log.info("download complete: fetched=%d skipped=%d no_data=%d errors=%d",
             fetched, skipped, no_data, errors)
    return {"fetched": fetched, "skipped": skipped, "no_data": no_data, "errors": errors}
