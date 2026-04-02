from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

from market_data.common.paths import duckdb_path, silver_path, gold_path, get_settings


def connect(db_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    p = db_path or duckdb_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p))


def register_parquet_view(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    parquet_dir: Path,
) -> None:
    pattern = str(parquet_dir / "**/*.parquet") if parquet_dir.is_dir() else str(parquet_dir)
    pattern = pattern.replace("\\", "/")
    con.execute(
        f"CREATE OR REPLACE VIEW {view_name} AS "
        f"SELECT * FROM read_parquet('{pattern}', hive_partitioning=true)"
    )


def register_all_views(con: Optional[duckdb.DuckDBPyConnection] = None) -> duckdb.DuckDBPyConnection:
    """Register views for all silver and gold datasets that exist on disk."""
    if con is None:
        con = connect()

    settings = get_settings()

    silver_datasets = [
        "instrument_master",
        "instrument_symbol_history",
        "security_master", "symbol_map_history",
        "prices_1d_unadjusted",
        "corporate_actions", "adjustment_factors", "prices_1d_split_adjusted",
        "filings", "fundamentals_reported", "fundamentals_asof_daily",
        "macro_observations_vintage", "macro_asof_daily",
        "universe_membership", "benchmark_prices_daily", "trading_calendar",
    ]
    for name in silver_datasets:
        p = silver_path(name, settings)
        if p.exists():
            register_parquet_view(con, name, p)

    gold_datasets = [
        "gold_daily_panel", "gold_intraday_panel",
        "gold_macro_context", "gold_benchmark_context", "gold_feature_base",
    ]
    for name in gold_datasets:
        p = gold_path(name, settings)
        if p.exists():
            register_parquet_view(con, name, p)

    return con
