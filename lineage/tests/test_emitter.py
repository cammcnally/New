from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

pytest.importorskip("openlineage.client")

from lineage.emitter import PipelineLineageEmitter
from lineage.facets import pipeline_config_facet


def _latest_json(tmp_path: Path) -> dict:
    files = sorted(tmp_path.glob("*.json"))
    assert files, "expected at least one lineage JSON file"
    return json.loads(files[-1].read_text(encoding="utf-8"))


def test_start_event_structure(tmp_path: Path) -> None:
    run_id = str(uuid.uuid4())
    out = tmp_path / "events"
    emitter = PipelineLineageEmitter(
        namespace="swing-pipeline",
        job_name="pipeline-run",
        transport="file",
        output_dir=str(out),
    )
    cfg = pipeline_config_facet({"threshold_search_corrected": True})
    emitter.emit_start(
        run_id,
        [{"namespace": "csv", "name": "inputs/prices.csv"}],
        config_facet=cfg,
    )
    data = _latest_json(out)
    assert data["eventType"] == "START"
    assert data["run"]["runId"] == run_id
    assert data["job"]["namespace"] == "swing-pipeline"
    assert data["job"]["name"] == "pipeline-run"
    assert "producer" in data and data["producer"]
    assert "eventTime" in data and "T" in data["eventTime"]
    assert data["inputs"]
    assert data["inputs"][0]["namespace"] == "csv"
    assert data["inputs"][0]["name"] == "inputs/prices.csv"
    assert data["run"]["facets"]


def test_complete_event_structure(tmp_path: Path) -> None:
    run_id = str(uuid.uuid4())
    out = tmp_path / "events"
    emitter = PipelineLineageEmitter(output_dir=str(out))
    emitter.emit_complete(
        run_id,
        [{"namespace": "reports", "name": "metrics.parquet"}],
    )
    data = _latest_json(out)
    assert data["eventType"] == "COMPLETE"
    assert data["run"]["runId"] == run_id
    assert data["job"]["namespace"] == "swing-pipeline"
    assert data["job"]["name"] == "pipeline-run"
    assert "producer" in data and data["producer"]
    assert data["outputs"]
    assert data["outputs"][0]["name"] == "metrics.parquet"


def test_fail_event_structure(tmp_path: Path) -> None:
    run_id = str(uuid.uuid4())
    out = tmp_path / "events"
    emitter = PipelineLineageEmitter(output_dir=str(out))
    emitter.emit_fail(run_id, "validation failed")
    data = _latest_json(out)
    assert data["eventType"] == "FAIL"
    assert data["run"]["runId"] == run_id
    assert data["job"]["namespace"] == "swing-pipeline"
    assert "producer" in data and data["producer"]
    facets = data["run"]["facets"]
    assert facets
    err_key = "https://openlineage.io/spec/facets/1-0-1/ErrorMessageRunFacet.json#/$defs/ErrorMessageRunFacet"
    assert err_key in facets
    assert "validation failed" in facets[err_key]["message"]
