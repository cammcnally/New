"""Normalize SEC submissions JSON into typed bronze Parquet."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.sec_submissions")


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str = "",
    end_date: str = "",
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("sec", "submissions", settings)
    out_path = bronze_path("sec_submissions", settings) / "submissions.parquet"

    if full_refresh and out_path.exists():
        out_path.unlink()

    all_rows: list[dict] = []
    file_count = 0

    for json_file in sorted(raw_dir.glob("CIK*.json")):
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            log.warning("failed to parse: %s", json_file)
            continue

        cik = data.get("cik", "")
        company_name = data.get("name", "")
        tickers = data.get("tickers", [])
        exchanges = data.get("exchanges", [])

        for filing in data.get("filings", []):
            all_rows.append({
                "cik": cik,
                "company_name": company_name,
                "ticker_primary": tickers[0] if tickers else "",
                "exchange_primary": exchanges[0] if exchanges else "",
                "accession_no": filing.get("accessionNumber", ""),
                "form_type": filing.get("form", ""),
                "filing_date": filing.get("filingDate", ""),
                "accepted_at": filing.get("acceptanceDateTime", ""),
                "primary_document": filing.get("primaryDocument", ""),
                "is_xbrl": bool(filing.get("isXBRL", 0)),
                "source_vendor": "sec",
            })
        file_count += 1

    if not all_rows:
        log.warning("no SEC submissions data found")
        return {"rows": 0}

    df = pl.DataFrame(all_rows)
    df = df.with_columns([
        pl.col("filing_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("accepted_at").str.strptime(
            pl.Datetime("us", "UTC"), "%Y-%m-%dT%H:%M:%S%.f", strict=False
        ),
        pl.lit(utc_now()).alias("loaded_at").cast(pl.Datetime("us", "UTC")),
    ])

    rows = write_parquet(df, out_path)
    log.info("bronze sec_submissions: %d rows from %d files", rows, file_count)
    return {"rows": rows, "files": file_count}
