"""Build silver filings from bronze SEC submissions joined to security_master."""
from __future__ import annotations

import polars as pl

from market_data.common.dates import parse_date, utc_now
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import bronze_path, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.filings")


def _norm_cik(name: str = "cik") -> pl.Expr:
    c = pl.col(name)
    return pl.when(c.is_null()).then(None).otherwise(c.cast(pl.Utf8).str.strip_chars().str.zfill(10))


def _sec_index_url(cik: pl.Expr, accession_no: pl.Expr) -> pl.Expr:
    """SEC Archives index URL for a filing (CIK path segment + accession folder)."""
    cik_int = (
        cik.cast(pl.Utf8)
        .str.strip_chars()
        .cast(pl.Int64, strict=False)
        .cast(pl.Utf8)
        .fill_null(pl.lit("0"))
    )
    acc_flat = accession_no.cast(pl.Utf8).str.replace_all("-", "")
    return (
        pl.lit("https://www.sec.gov/Archives/edgar/data/")
        + cik_int
        + pl.lit("/")
        + acc_flat
        + pl.lit("/")
        + accession_no.cast(pl.Utf8)
        + pl.lit("-index.htm")
    )


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    sub_path = bronze_path("sec_submissions", settings) / "submissions.parquet"
    sm_path = silver_path("security_master", settings) / "security_master.parquet"

    if not sub_path.exists():
        log.warning("bronze sec_submissions not found: %s", sub_path)
        return {"rows": 0}
    if not sm_path.exists():
        log.warning("silver security_master not found: %s", sm_path)
        return {"rows": 0}

    sub = read_parquet(sub_path).collect()
    sm = read_parquet(sm_path).collect().filter(pl.col("cik").is_not_null())

    if len(sub) == 0 or len(sm) == 0:
        log.warning("empty submissions or security_master with CIK")
        return {"rows": 0}

    sub = sub.with_columns(_norm_cik("cik").alias("cik"))
    sm_keys = sm.with_columns(_norm_cik("cik").alias("cik")).select(["cik", "sid"]).unique(subset=["cik"])

    df = sub.join(sm_keys, on="cik", how="inner")

    sd, ed = parse_date(start_date), parse_date(end_date)
    df = df.filter(pl.col("filing_date").is_between(sd, ed))

    loaded = utc_now()
    df = df.with_columns(
        pl.col("form_type").cast(pl.Utf8).str.contains("/A").alias("is_amendment"),
        _sec_index_url(pl.col("cik"), pl.col("accession_no")).alias("source_url"),
        pl.lit(None).cast(pl.Date).alias("period_end"),
        pl.lit(loaded).cast(pl.Datetime("us", "UTC")).alias("loaded_at"),
    ).select(
        [
            "sid",
            "cik",
            "accession_no",
            "form_type",
            pl.col("filing_date").alias("filed_at"),
            "accepted_at",
            "period_end",
            "is_amendment",
            "source_url",
            "loaded_at",
        ]
    )

    out_path = silver_path("filings", settings) / "filings.parquet"
    if full_refresh and out_path.exists():
        out_path.unlink()

    written = write_parquet(df, out_path)
    log.info("silver filings: %d rows -> %s", written, out_path)
    return {"rows": written}
