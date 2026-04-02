from __future__ import annotations

from pathlib import Path

import pytest

from market_data.common.manifest import (
    build_dataset_build_id,
    build_manifest,
    read_manifest,
    write_manifest,
)

pytestmark = pytest.mark.ingestion


def test_build_manifest() -> None:
    m = build_manifest(
        datasets=[
            {
                "name": "test_ds",
                "layer": "bronze",
                "source_inputs": ["a"],
                "row_count": 3,
                "partitions": [],
                "content_hash": "",
            }
        ],
        run_id="run-test-1",
    )
    assert m["run_id"] == "run-test-1"
    assert m["dataset_build_id"] == "run-test-1"
    assert m["manifest_version"] == "market_data_dataset_manifest_v1"
    assert "git_commit" in m and m["git_commit"]
    assert "python_version" in m and m["python_version"]
    assert "generated_at_utc" in m and m["generated_at_utc"]
    assert m["verification_artifacts"] == []
    assert m["deferred_components"] == []
    assert len(m["datasets"]) == 1
    assert m["datasets"][0]["name"] == "test_ds"


def test_write_read_manifest(tmp_path: Path) -> None:
    m = build_manifest(datasets=[], run_id="r2")
    path = tmp_path / "manifests" / "run.json"
    write_manifest(m, path)
    assert read_manifest(path) == m


def test_build_dataset_build_id_is_stable() -> None:
    datasets = [
        {
            "name": "prices_1d_unadjusted",
            "layer": "silver",
            "source_inputs": ["bronze/yfinance"],
            "row_count": 10,
            "partitions": ["year=2024"],
            "content_hash": "abc123",
        },
        {
            "name": "instrument_master",
            "layer": "silver",
            "source_inputs": ["bronze/av_listing_status"],
            "row_count": 2,
            "partitions": [],
            "content_hash": "def456",
        },
    ]
    first = build_dataset_build_id(datasets)
    second = build_dataset_build_id(list(reversed(datasets)))

    assert first == second
    assert first.startswith("dataset-build-")
