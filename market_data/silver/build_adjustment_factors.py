"""Silver: cumulative split adjustment factors from corporate actions."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import silver_path
from market_data.common.schema_registry import ADJUSTMENT_FACTORS
from market_data.common.settings import IngestionSettings

log = get_logger("silver.adjustment_factors")


def _factors_for_sid(sid: str, splits: pl.DataFrame) -> pl.DataFrame:
    """One row per split ex_date with cumulative factors (newest split gets cum=1.0)."""
    if len(splits) == 0:
        return pl.DataFrame(
            schema={
                "sid": pl.Utf8,
                "effective_date": pl.Date,
                "split_factor": pl.Float64,
                "dividend_factor": pl.Float64,
                "cum_split_factor": pl.Float64,
                "cum_total_return_factor": pl.Float64,
                "loaded_at": pl.Datetime("us", "UTC"),
            }
        )

    s_asc = splits.sort("ex_date")
    ex_dates = s_asc.get_column("ex_date").to_list()
    coeffs = s_asc.get_column("split_coefficient").to_list()

    loaded = utc_now()
    cum = 1.0
    rows: list[dict] = []

    for i in range(len(ex_dates) - 1, -1, -1):
        ex_d = ex_dates[i]
        c = float(coeffs[i])
        inv = 1.0 / c if c != 0.0 else float("nan")
        rows.append(
            {
                "sid": sid,
                "effective_date": ex_d,
                "split_factor": inv,
                "dividend_factor": 1.0,
                "cum_split_factor": cum,
                "cum_total_return_factor": cum,
                "loaded_at": loaded,
            }
        )
        cum *= inv

    return pl.DataFrame(rows)


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    _ = (start_date, end_date)  # reserved for incremental rebuilds
    ca_path = silver_path("corporate_actions", settings) / "corporate_actions.parquet"
    out_dir = silver_path("adjustment_factors", settings)

    if not ca_path.exists():
        log.warning("silver corporate_actions not found: %s", ca_path)
        return {"rows": 0}

    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    ca = read_parquet(ca_path).filter(pl.col("action_type") == "split").collect()

    if len(ca) == 0:
        log.warning("no split rows in corporate_actions")
        return {"rows": 0}

    combined_splits = ca.group_by(["sid", "ex_date"]).agg(
        pl.col("split_coefficient").cast(pl.Float64).product().alias("split_coefficient")
    )

    parts: list[pl.DataFrame] = []
    for sid in combined_splits.get_column("sid").unique().to_list():
        splits = combined_splits.filter(pl.col("sid") == sid).select(
            "ex_date", "split_coefficient"
        )
        parts.append(_factors_for_sid(str(sid), splits))

    out = pl.concat(parts, how="vertical")

    for col, dtype in ADJUSTMENT_FACTORS.items():
        if col in out.columns and out.schema[col] != dtype:
            out = out.with_columns(pl.col(col).cast(dtype))

    validate_contract_df("adjustment_factors", out)

    out = out.with_columns(pl.col("effective_date").dt.year().alias("year"))

    rows = write_parquet(out, out_dir, partition_by=["year"])
    log.info("silver adjustment_factors: %d rows", rows)
    return {"rows": rows}

