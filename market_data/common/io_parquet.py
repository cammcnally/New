from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Sequence

import polars as pl

COMPRESSION: Literal["zstd"] = "zstd"


def write_parquet(
    df: pl.DataFrame | pl.LazyFrame,
    base_path: Path,
    *,
    partition_by: Optional[Sequence[str]] = None,
) -> int:
    """Write a Polars DataFrame to Parquet with ZSTD compression.

    Returns the number of rows written. When ``partition_by`` is given, data is
    written into Hive-style directories under *base_path*.
    """
    if isinstance(df, pl.LazyFrame):
        df = df.collect()

    row_count = len(df)
    if row_count == 0:
        return 0

    if partition_by:
        _write_partitioned(df, base_path, list(partition_by))
    else:
        base_path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(base_path, compression=COMPRESSION)

    return row_count


def _write_partitioned(
    df: pl.DataFrame, base_path: Path, partition_cols: list[str]
) -> None:
    for values, part_df in df.group_by(partition_cols):
        if not isinstance(values, tuple):
            values = (values,)
        part_dir = base_path
        for col, val in zip(partition_cols, values):
            part_dir = part_dir / f"{col}={val}"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_df.drop(partition_cols).write_parquet(
            part_dir / "part-000.parquet", compression=COMPRESSION
        )


def read_parquet(
    path: Path,
    *,
    columns: Optional[list[str]] = None,
) -> pl.LazyFrame:
    """Read Parquet files (single file or Hive-partitioned directory)."""
    target = (path / "**/*.parquet").as_posix() if path.is_dir() else path.as_posix()
    lf = pl.scan_parquet(target, hive_partitioning=True)
    if columns:
        lf = lf.select(columns)
    return lf


def row_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_dir() and not any(path.rglob("*.parquet")):
        return 0
    return read_parquet(path).select(pl.len()).collect().item()
