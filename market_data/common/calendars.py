from __future__ import annotations

from datetime import date
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=4)
def _get_calendar(name: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(name)


def nyse() -> xcals.ExchangeCalendar:
    return _get_calendar("XNYS")


def trading_days(start: date, end: date, exchange: str = "XNYS") -> list[date]:
    cal = _get_calendar(exchange)
    sessions = cal.sessions_in_range(
        pd.Timestamp(start), pd.Timestamp(end)
    )
    return [s.date() for s in sessions]


def is_trading_day(d: date, exchange: str = "XNYS") -> bool:
    cal = _get_calendar(exchange)
    return cal.is_session(pd.Timestamp(d))


def is_early_close(d: date, exchange: str = "XNYS") -> bool:
    cal = _get_calendar(exchange)
    ts = pd.Timestamp(d)
    if not cal.is_session(ts):
        return False
    return ts in cal.early_closes


def session_open_close(d: date, exchange: str = "XNYS") -> tuple[pd.Timestamp, pd.Timestamp]:
    cal = _get_calendar(exchange)
    ts = pd.Timestamp(d)
    return cal.session_open(ts), cal.session_close(ts)
