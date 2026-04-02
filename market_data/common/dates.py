from __future__ import annotations

from datetime import date, datetime, timezone


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def date_range(start: date, end: date) -> list[date]:
    """Inclusive calendar-day range."""
    from datetime import timedelta

    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days
