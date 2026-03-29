from __future__ import annotations

import pandas as pd
import pytest

from feature_registry.retrieval import (
    PIT_SOURCE_TIME_COL,
    pit_merge,
    validate_pit_correctness,
)


@pytest.fixture
def entity_col() -> str:
    return "ticker"


@pytest.fixture
def time_col() -> str:
    return "timestamp_utc"


def test_pit_merge_no_future_leak(entity_col: str, time_col: str) -> None:
    """Backward as-of merge must never attach a right row dated after the left row."""
    ts_left = pd.to_datetime(
        ["2024-01-01 10:00", "2024-01-01 10:05", "2024-01-01 10:10"], utc=True
    )
    ts_right = pd.to_datetime(
        ["2024-01-01 10:00", "2024-01-01 10:05", "2024-01-01 10:20"], utc=True
    )
    left = pd.DataFrame({entity_col: "AAA", time_col: ts_left, "left_id": [0, 1, 2]})
    right = pd.DataFrame(
        {
            entity_col: "AAA",
            time_col: ts_right,
            "feat": [1.0, 2.0, 999.0],
        }
    )
    merged = pit_merge(left, right, entity_col, time_col)
    assert PIT_SOURCE_TIME_COL in merged.columns
    assert merged.loc[2, "feat"] == 2.0
    assert merged.loc[2, PIT_SOURCE_TIME_COL] == ts_right[1]
    assert (merged[PIT_SOURCE_TIME_COL] <= merged[time_col]).all()


def test_validate_pit_correctness_passes_after_pit_merge(
    entity_col: str, time_col: str
) -> None:
    ts = pd.to_datetime(["2024-01-01 12:00", "2024-01-01 12:01"], utc=True)
    left = pd.DataFrame({entity_col: "X", time_col: ts})
    right = pd.DataFrame(
        {entity_col: "X", time_col: ts, "feat": [10.0, 20.0]}
    )
    merged = pit_merge(left, right, entity_col, time_col)
    assert validate_pit_correctness(merged, "feat", time_col, entity_col) is True


def test_validate_pit_correctness_fails_on_future_source(
    entity_col: str, time_col: str
) -> None:
    ts = pd.to_datetime(["2024-01-01 12:00"], utc=True)
    future_src = pd.to_datetime(["2024-01-01 13:00"], utc=True)
    bad = pd.DataFrame(
        {
            entity_col: "X",
            time_col: ts,
            "feat": [1.0],
            PIT_SOURCE_TIME_COL: future_src,
        }
    )
    assert validate_pit_correctness(bad, "feat", time_col, entity_col) is False


def test_validate_pit_correctness_false_without_source_column(
    entity_col: str, time_col: str
) -> None:
    df = pd.DataFrame(
        {
            entity_col: "X",
            time_col: pd.to_datetime(["2024-01-01"], utc=True),
            "feat": [1.0],
        }
    )
    assert validate_pit_correctness(df, "feat", time_col, entity_col) is False
