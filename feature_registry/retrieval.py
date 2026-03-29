from __future__ import annotations

import pandas as pd

PIT_SOURCE_TIME_COL = "__pit_source_time"


def pit_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    entity_col: str,
    time_col: str,
) -> pd.DataFrame:
    """
    Point-in-time merge: for each row in ``left``, attach the most recent ``right`` row
    at or before the same (entity, time) using backward ``merge_asof``.
    Adds ``__pit_source_time`` = timestamp from the matched right row (NaT if no match).
    """
    L = left.sort_values([entity_col, time_col], kind="mergesort").copy()
    R = right.sort_values([entity_col, time_col], kind="mergesort").copy()
    R = R.copy()
    R[PIT_SOURCE_TIME_COL] = R[time_col]
    merged = pd.merge_asof(
        L,
        R,
        on=time_col,
        by=entity_col,
        direction="backward",
        suffixes=("", "_pit_right"),
    )
    return merged


def validate_pit_correctness(
    df: pd.DataFrame,
    feature_col: str,
    time_col: str,
    entity_col: str,
    source_time_col: str | None = None,
) -> bool:
    """
    Return True when every non-null ``source_time_col`` value is <= ``time_col`` on the same row
    (no feature row was sourced from a future timestamp). Rows with null source time are ignored.

    If ``source_time_col`` is omitted, uses ``__pit_source_time`` if present; otherwise returns
    False (cannot verify PIT without a source timestamp).
    """
    st_col = source_time_col or PIT_SOURCE_TIME_COL
    if st_col not in df.columns:
        return False
    t = pd.to_datetime(df[time_col], utc=True)
    st = pd.to_datetime(df[st_col], utc=True)
    mask = st.notna()
    if not mask.any():
        return True
    ok = st[mask] <= t[mask]
    if feature_col not in df.columns:
        return False
    return bool(ok.all())
