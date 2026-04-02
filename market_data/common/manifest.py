from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_data.common.build_contract import ROW_STATES, default_report_inventory
from market_data.common.hashing import hash_bytes, hash_file
from market_data.common.settings import IngestionSettings


def get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    for env_name in ("GITHUB_SHA", "CI_COMMIT_SHA", "GIT_COMMIT"):
        value = os.environ.get(env_name)
        if value:
            return value
    return "unknown"


def python_version() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def stable_content_id(prefix: str, content_hash: str, *, length: int = 16) -> str:
    return f"{prefix}-{content_hash[:length]}"


def build_dataset_build_id(datasets: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "name": item.get("name"),
            "layer": item.get("layer"),
            "source_inputs": item.get("source_inputs", []),
            "row_count": item.get("row_count", 0),
            "partitions": item.get("partitions", []),
            "content_hash": item.get("content_hash", ""),
        }
        for item in sorted(datasets, key=lambda value: (str(value.get("layer")), str(value.get("name"))))
    ]
    digest = hash_bytes(json.dumps(normalized, sort_keys=True).encode("utf-8"))
    return stable_content_id("dataset-build", digest)


def build_dataset_entry(
    name: str,
    layer: str,
    source_inputs: list[str],
    data_path: Path,
    row_count: int,
) -> dict[str, Any]:
    partitions: list[str] = []
    content_hash = ""

    if data_path.is_dir():
        partitions = sorted(
            p.name for p in data_path.iterdir() if p.is_dir() and "=" in p.name
        )
        parquet_files = sorted(data_path.rglob("*.parquet"))
        if parquet_files:
            combined = "|".join(hash_file(f) for f in parquet_files)
            from market_data.common.hashing import hash_bytes
            content_hash = hash_bytes(combined.encode())
    elif data_path.is_file():
        content_hash = hash_file(data_path)

    return {
        "name": name,
        "layer": layer,
        "source_inputs": source_inputs,
        "row_count": row_count,
        "partitions": partitions,
        "content_hash": content_hash,
    }


def build_manifest(
    datasets: list[dict[str, Any]],
    run_id: str | None = None,
    verification_artifacts: list[dict[str, Any]] | None = None,
    deferred_components: list[str] | None = None,
    dataset_build_id: str | None = None,
    reports: dict[str, Any] | None = None,
    domain_statuses: dict[str, Any] | None = None,
    final_status: str = "unknown",
    canonical_export_ready: bool = False,
    compatibility_fallback_used: bool = False,
) -> dict[str, Any]:
    build_id = run_id or datetime.now(timezone.utc).isoformat()
    resolved_dataset_build_id = dataset_build_id or build_id
    report_inventory = default_report_inventory()
    if reports:
        report_inventory.update(reports)
    return {
        "manifest_version": "market_data_dataset_manifest_v1",
        "run_id": build_id,
        "dataset_build_id": resolved_dataset_build_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "python_version": python_version(),
        "row_state_model": list(ROW_STATES),
        "reports": report_inventory,
        "domain_statuses": domain_statuses or {},
        "final_status": final_status,
        "canonical_export_ready": canonical_export_ready,
        "compatibility_fallback_used": compatibility_fallback_used,
        "verification_artifacts": verification_artifacts or [],
        "deferred_components": deferred_components or [],
        "datasets": datasets,
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)


def read_manifest(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def dataset_manifest_path(settings: IngestionSettings | None) -> Path:
    from market_data.common.paths import manifest_dir

    return manifest_dir(settings) / "dataset_manifest.json"


def current_dataset_build_id(settings: IngestionSettings | None) -> str | None:
    path = dataset_manifest_path(settings)
    if not path.exists():
        return None
    manifest = read_manifest(path)
    raw = manifest.get("dataset_build_id")
    return str(raw) if raw else None


def build_export_manifest(
    *,
    output_path: Path,
    contract_name: str,
    start_date: str,
    end_date: str,
    row_count: int,
    ticker_count: int,
    dataset_build_id: str | None,
    verification_artifacts: list[dict[str, Any]] | None = None,
    deferred_components: list[str] | None = None,
    side_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not dataset_build_id:
        raise ValueError("dataset_build_id is required for export manifests")
    content_hash = hash_file(output_path)
    export_panel_version_id = stable_content_id("export-panel", content_hash)
    return {
        "manifest_version": "market_data_export_manifest_v1",
        "export_panel_version_id": export_panel_version_id,
        "dataset_build_id": dataset_build_id,
        "contract_name": contract_name,
        "output_path": str(output_path),
        "start_date": start_date,
        "end_date": end_date,
        "row_count": row_count,
        "ticker_count": ticker_count,
        "content_hash": content_hash,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "python_version": python_version(),
        "verification_artifacts": verification_artifacts or [],
        "deferred_components": deferred_components or [],
        "side_artifacts": side_artifacts or {},
    }


def write_export_manifest(manifest: dict[str, Any], output_path: Path) -> Path:
    manifest_path = Path(str(output_path) + ".manifest.json")
    write_manifest(manifest, manifest_path)
    return manifest_path


# ── Watermark ─────────────────────────────────────────────────────────────────

def watermark_path(settings: IngestionSettings | None) -> Path:
    from market_data.common.paths import manifest_dir
    return manifest_dir(settings) / "sync_watermark.json"


def read_watermark(settings: IngestionSettings | None) -> dict[str, Any] | None:
    wp = watermark_path(settings)
    if not wp.exists():
        return None
    with open(wp) as f:
        return json.load(f)


def write_watermark(
    settings: IngestionSettings | None,
    *,
    start_date: str,
    end_date: str,
    completed_at: str | None = None,
    phase: str = "bootstrap",
) -> Path:
    wp = watermark_path(settings)
    data = {
        "start_date": start_date,
        "end_date": end_date,
        "completed_at": completed_at or datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "python_version": python_version(),
        "git_commit": get_git_commit(),
    }
    wp.parent.mkdir(parents=True, exist_ok=True)
    with open(wp, "w") as f:
        json.dump(data, f, indent=2)
    return wp
