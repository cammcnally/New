"""Build silver trading_calendar (session schedule) using exchange_calendars."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import polars as pl

from market_data.common.calendars import is_early_close, is_trading_day, session_open_close
from market_data.common.dates import date_range, parse_date, utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.trading_calendar")

_DEFAULT_EXCHANGE_LABEL = "NYSE"
_CALENDAR_NAME = "XNYS"


def _session_ts_to_utc(ts: pd.Timestamp) -> datetime | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("America/New_York")
    else:
        t = t.tz_convert("America/New_York")
    return t.tz_convert(timezone.utc).to_pydatetime()


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = full_refresh

    sd = parse_date(start_date)
    ed = parse_date(end_date)
    days = date_range(sd, ed)
    loaded = utc_now()

    rows: list[dict[str, object]] = []
    for d in days:
        is_open = is_trading_day(d, exchange=_CALENDAR_NAME)
        mo: datetime | None = None
        mc: datetime | None = None
        early = False
        if is_open:
            o, c = session_open_close(d, exchange=_CALENDAR_NAME)
            mo = _session_ts_to_utc(o)
            mc = _session_ts_to_utc(c)
            early = is_early_close(d, exchange=_CALENDAR_NAME)

        rows.append(
            {
                "trade_date": d,
                "exchange": _DEFAULT_EXCHANGE_LABEL,
                "is_trading_day": is_open,
                "market_open_utc": mo,
                "market_close_utc": mc,
                "is_early_close": early,
                "loaded_at": loaded,
            }
        )

    df = pl.DataFrame(rows)
    df = validate_contract_df("trading_calendar", df)
    out_path = silver_path("trading_calendar", settings) / "trading_calendar.parquet"
    written = write_parquet(df, out_path)
    log.info("silver trading_calendar: %d rows -> %s", written, out_path)
    return {"rows": written}
