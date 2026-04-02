from __future__ import annotations

import pytest

from lineage.facets import build_references_dataset_facet


def test_build_references_dataset_facet_includes_build_ids() -> None:
    facet = build_references_dataset_facet(
        dataset_build_id="dataset-build-1",
        export_panel_version_id="export-panel-1",
        content_hash="abc123",
        contract_name="export_panel",
        manifest_path="panel.csv.manifest.json",
        output_path="panel.csv",
    )

    [(facet_key, payload)] = list(facet.items())

    assert "BuildReferencesDatasetFacet" in facet_key
    assert payload["dataset_build_id"] == "dataset-build-1"
    assert payload["export_panel_version_id"] == "export-panel-1"
    assert payload["manifest_path"] == "panel.csv.manifest.json"


def test_dataset_schema_facet_emits_openlineage_schema_facet() -> None:
    pytest.importorskip("openlineage.client")

    from lineage.facets import dataset_schema_facet

    facet = dataset_schema_facet(
        ["ticker", "timestamp_utc"],
        {"ticker": "string", "timestamp_utc": "datetime"},
    )

    assert len(facet) == 1
    assert "SchemaDatasetFacet" in next(iter(facet.keys()))
