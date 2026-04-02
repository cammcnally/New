"""Build silver fundamentals_reported from bronze SEC company facts."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import bronze_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.fundamentals_reported")


def _norm_cik(name: str = "cik") -> pl.Expr:
    c = pl.col(name)
    return pl.when(c.is_null()).then(None).otherwise(c.cast(pl.Utf8).str.strip_chars().str.zfill(10))


def _fiscal_quarter() -> pl.Expr:
    fp = pl.col("fiscal_period").cast(pl.Utf8).str.strip_chars().str.to_uppercase()
    return (
        pl.when(fp == "Q1")
        .then(1)
        .when(fp == "Q2")
        .then(2)
        .when(fp == "Q3")
        .then(3)
        .when(fp == "Q4")
        .then(4)
        .when(fp == "FY")
        .then(4)
        .otherwise(None)
        .cast(pl.Int32)
    )


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    facts_dir = bronze_path("sec_companyfacts", settings)
    sub_path = bronze_path("sec_submissions", settings) / "submissions.parquet"
    sm_path = silver_path("security_master", settings) / "security_master.parquet"

    if not facts_dir.exists():
        log.warning("bronze sec_companyfacts not found: %s", facts_dir)
        return {"rows": 0}
    if not sm_path.exists():
        log.warning("silver security_master not found: %s", sm_path)
        return {"rows": 0}

    lf = read_parquet(facts_dir)
    df = lf.collect()

    if len(df) == 0:
        log.warning("bronze sec_companyfacts is empty")
        return {"rows": 0}

    sm = read_parquet(sm_path).collect().filter(pl.col("cik").is_not_null())
    sm = sm.with_columns(_norm_cik("cik").alias("cik")).select(["cik", "sid"]).unique(subset=["cik"])

    df = df.with_columns(_norm_cik("cik").alias("cik")).join(sm, on="cik", how="inner")

    if sub_path.exists():
        subs = read_parquet(sub_path).collect()
        acc_accept = subs.select(["accession_no", "accepted_at"]).unique(subset=["accession_no"])
        df = df.join(acc_accept, on="accession_no", how="left")
    else:
        df = df.with_columns(pl.lit(None).cast(pl.Datetime("us", "UTC")).alias("accepted_at"))

    sd, ed = parse_date(start_date), parse_date(end_date)
    df = df.filter(pl.col("end_date").is_between(sd, ed))

    loaded = utc_now()
    df = df.with_columns(
        pl.col("concept").alias("metric_name"),
        pl.col("value").alias("metric_value"),
        pl.col("taxonomy").alias("statement_type"),
        pl.col("start_date").alias("period_start"),
        pl.col("end_date").alias("period_end"),
        _fiscal_quarter().alias("fiscal_quarter"),
        pl.lit(loaded).cast(pl.Datetime("us", "UTC")).alias("loaded_at"),
    ).select(
        [
            "sid",
            "accession_no",
            "metric_name",
            "metric_value",
            "unit",
            "statement_type",
            "period_start",
            "period_end",
            "fiscal_year",
            "fiscal_quarter",
            "accepted_at",
            "loaded_at",
        ]
    )

    df = df.with_columns(pl.col("period_end").dt.year().alias("year"))

    out_dir = silver_path("fundamentals_reported", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    written = write_parquet(df, out_dir, partition_by=["year"])
    log.info("silver fundamentals_reported: %d rows -> %s", written, out_dir)
    return {"rows": written}
