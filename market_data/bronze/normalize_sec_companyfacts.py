"""Normalize SEC EDGAR company facts (XBRL) JSON into typed bronze Parquet."""
from __future__ import annotations

import json

import polars as pl

from market_data.common.dates import utc_now
from market_data.common.io_parquet import write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import raw_path, bronze_path
from market_data.common.settings import IngestionSettings

log = get_logger("bronze.sec_companyfacts")


def _flatten_facts(data: dict, cik: str) -> list[dict]:
    """Flatten the nested XBRL facts structure into rows."""
    rows: list[dict] = []
    facts = data.get("facts", {})

    for taxonomy, concepts in facts.items():
        for concept_name, concept_data in concepts.items():
            units = concept_data.get("units", {})
            for unit_type, entries in units.items():
                for entry in entries:
                    rows.append({
                        "cik": cik,
                        "taxonomy": taxonomy,
                        "concept": concept_name,
                        "label": concept_data.get("label", ""),
                        "unit": unit_type,
                        "value": entry.get("val"),
                        "start_date": entry.get("start"),
                        "end_date": entry.get("end"),
                        "filed_date": entry.get("filed"),
                        "accession_no": entry.get("accn", ""),
                        "form_type": entry.get("form", ""),
                        "fiscal_year": entry.get("fy"),
                        "fiscal_period": entry.get("fp", ""),
                        "frame": entry.get("frame", ""),
                    })
    return rows


def normalize(
    *,
    settings: IngestionSettings,
    start_date: str = "",
    end_date: str = "",
    full_refresh: bool = False,
) -> dict[str, object]:
    raw_dir = raw_path("sec", "companyfacts", settings)
    out_dir = bronze_path("sec_companyfacts", settings)

    if full_refresh and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    all_rows: list[dict] = []
    file_count = 0

    for json_file in sorted(raw_dir.glob("CIK*_facts.json")):
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            log.warning("failed to parse: %s", json_file)
            continue

        cik = data.get("cik", json_file.stem.split("_")[0].replace("CIK", ""))
        rows = _flatten_facts(data, str(cik))
        all_rows.extend(rows)
        file_count += 1

    if not all_rows:
        log.warning("no SEC companyfacts data found")
        return {"rows": 0}

    df = pl.DataFrame(all_rows)
    df = df.with_columns([
        pl.col("value").cast(pl.Float64, strict=False),
        pl.col("start_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("end_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("filed_date").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("fiscal_year").cast(pl.Int32, strict=False),
        pl.lit("sec").alias("source_vendor"),
        pl.lit(utc_now()).alias("loaded_at").cast(pl.Datetime("us", "UTC")),
    ])

    df = df.with_columns(
        pl.col("end_date").dt.year().fill_null(2000).alias("year")
    )

    rows = write_parquet(df, out_dir, partition_by=["year"])
    log.info("bronze sec_companyfacts: %d rows from %d files", rows, file_count)
    return {"rows": rows, "files": file_count}
