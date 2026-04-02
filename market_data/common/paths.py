from __future__ import annotations

from pathlib import Path

from market_data.common.settings import IngestionSettings, get_settings


LAYER_NAMES = ("raw", "bronze", "silver", "gold", "qa", "manifests")


def lake_root(settings: IngestionSettings | None = None) -> Path:
    return (settings or get_settings()).data_lake_root


def ensure_lake_dirs(settings: IngestionSettings | None = None) -> None:
    root = lake_root(settings)
    for layer in LAYER_NAMES:
        (root / layer).mkdir(parents=True, exist_ok=True)


def raw_path(source: str, dataset: str, settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "raw" / source / dataset


def bronze_path(dataset: str, settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "bronze" / dataset


def silver_path(dataset: str, settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "silver" / dataset


def gold_path(dataset: str, settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "gold" / dataset


def qa_dir(settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "qa"


def manifest_dir(settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "manifests"


def duckdb_path(settings: IngestionSettings | None = None) -> Path:
    return lake_root(settings) / "research.duckdb"
