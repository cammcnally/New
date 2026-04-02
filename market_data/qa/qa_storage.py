"""QA checks for data-lake storage integrity."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from market_data.common.io_parquet import row_count
from market_data.common.logging import get_logger
from market_data.common.paths import gold_path, manifest_dir, silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("qa.storage")

_PARTITION_SIZE_MAX_MB = 500
_PARTITION_SIZE_MIN_KB = 1

_DATASETS: dict[str, list[str]] = {
    "silver": [
        "instrument_master",
        "instrument_symbol_history",
        "security_master",
        "prices_1d_split_adjusted",
        "prices_1d_unadjusted",
        "universe_membership",
        "corporate_actions",
        "macro_observations_vintage",
        "macro_asof_daily",
        "benchmark_prices_daily",
    ],
    "gold": [
        "gold_daily_panel",
        "gold_intraday_panel",
        "gold_macro_context",
        "gold_benchmark_context",
        "gold_feature_base",
    ],
}


def _path_for(
    layer: str, dataset: str, settings: IngestionSettings
) -> Path:
    if layer == "silver":
        return silver_path(dataset, settings)
    return gold_path(dataset, settings)


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    for layer, datasets in _DATASETS.items():
        for ds in datasets:
            ds_path = _path_for(layer, ds, settings)
            if not ds_path.exists():
                continue

            pq_files = list(ds_path.rglob("*.parquet"))
            stats[f"{layer}/{ds}_file_count"] = len(pq_files)

            for pf in pq_files:
                size_mb = pf.stat().st_size / (1024 * 1024)
                if size_mb > _PARTITION_SIZE_MAX_MB:
                    warnings.append(
                        f"{layer}/{ds}: {pf.name} is {size_mb:.1f} MB "
                        f"(> {_PARTITION_SIZE_MAX_MB} MB)"
                    )
                size_kb = pf.stat().st_size / 1024
                if size_kb < _PARTITION_SIZE_MIN_KB and pf.stat().st_size > 0:
                    warnings.append(
                        f"{layer}/{ds}: {pf.name} is {size_kb:.2f} KB "
                        f"(suspiciously small)"
                    )

    for layer, datasets in _DATASETS.items():
        for ds in datasets:
            ds_path = _path_for(layer, ds, settings)
            if not ds_path.exists():
                continue

            pq_files = list(ds_path.rglob("*.parquet"))
            if len(pq_files) < 2:
                continue

            schemas: set[tuple[tuple[str, pl.DataType], ...]] = set()
            for pf in pq_files[:10]:
                lf = pl.scan_parquet(str(pf))
                col_sig = tuple(sorted(lf.schema.items()))
                schemas.add(col_sig)
            if len(schemas) > 1:
                warnings.append(
                    f"{layer}/{ds}: inconsistent schemas across "
                    f"{len(schemas)} variants"
                )
            stats[f"{layer}/{ds}_schema_variants"] = len(schemas)

    mdir = manifest_dir(settings)
    manifest_file = mdir / "dataset_manifest.json" if mdir.exists() else None
    if manifest_file and manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text())
            manifest_entries = {
                f"{entry.get('layer')}/{entry.get('name')}": entry
                for entry in manifest.get("datasets", [])
                if isinstance(entry, dict)
            }
            for layer, datasets in _DATASETS.items():
                for ds in datasets:
                    key = f"{layer}/{ds}"
                    ds_path = _path_for(layer, ds, settings)
                    if not ds_path.exists():
                        continue
                    current_rows = row_count(ds_path)
                    prev_entry = manifest_entries.get(key, {})
                    prev_rows = prev_entry.get("row_count", 0)
                    if prev_rows > 0:
                        delta_pct = abs(current_rows - prev_rows) / prev_rows * 100
                        stats[f"{key}_row_delta_pct"] = round(delta_pct, 2)
                        if delta_pct > 50:
                            warnings.append(
                                f"{key}: row count changed by {delta_pct:.1f}% "
                                f"({prev_rows} -> {current_rows})"
                            )
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"manifest read error: {exc}")

    log.info("qa_storage: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
