from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from market_data.common.io_parquet import list_parquet_files, read_parquet, row_count, write_parquet

pytestmark = pytest.mark.ingestion


def test_write_read_roundtrip(tmp_path: Path, sample_prices_df: pl.DataFrame) -> None:
    path = tmp_path / "px.parquet"
    write_parquet(sample_prices_df, path)
    back = read_parquet(path).collect()
    assert_frame_equal_ignore_order(sample_prices_df, back)


def test_write_partitioned(tmp_path: Path) -> None:
    df = pl.DataFrame(
        {
            "year": [2023, 2023, 2024],
            "sid": ["A", "B", "C"],
            "v": [1.0, 2.0, 3.0],
        }
    )
    base = tmp_path / "partitioned"
    write_parquet(df, base, partition_by=["year"])
    assert (base / "year=2023").is_dir()
    assert (base / "year=2024").is_dir()
    assert (base / "year=2023" / "part-000.parquet").is_file()
    loaded = read_parquet(base).collect().sort(["sid"])
    assert loaded["v"].to_list() == [1.0, 2.0, 3.0]
    assert set(loaded["year"].to_list()) == {2023, 2024}


def test_list_parquet_files_file_and_partitioned_dir(tmp_path: Path) -> None:
    single = tmp_path / "one.parquet"
    pl.DataFrame({"a": [1]}).write_parquet(single)
    assert list_parquet_files(single) == [single]
    base = tmp_path / "hive"
    write_parquet(
        pl.DataFrame({"y": [2023, 2024], "x": [1, 2]}),
        base,
        partition_by=["y"],
    )
    files = list_parquet_files(base)
    assert len(files) == 2
    assert all(f.suffix == ".parquet" for f in files)


def test_row_count(tmp_path: Path, sample_prices_df: pl.DataFrame) -> None:
    path = tmp_path / "counted.parquet"
    n = write_parquet(sample_prices_df, path)
    assert n == len(sample_prices_df)
    assert row_count(path) == len(sample_prices_df)


def assert_frame_equal_ignore_order(a: pl.DataFrame, b: pl.DataFrame) -> None:
    """Compare frames with same columns and rows (order-independent)."""
    assert set(a.columns) == set(b.columns)
    for c in a.columns:
        a = a.with_columns(pl.col(c).cast(b.schema[c]))
    a_sorted = a.sort(a.columns)
    b_sorted = b.sort(b.columns)
    assert a_sorted.shape == b_sorted.shape
    for c in a.columns:
        assert a_sorted[c].to_list() == b_sorted[c].to_list()
