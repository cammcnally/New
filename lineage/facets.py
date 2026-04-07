from __future__ import annotations

from typing import Any

_PIPELINE_CONFIG_FACET_KEY = (
    "https://swing-pipeline.local/spec/facets/1-0-0/PipelineConfigRunFacet.json"
    "#/$defs/PipelineConfigRunFacet"
)
_BUILD_REFERENCES_DATASET_FACET_KEY = (
    "https://swing-pipeline.local/spec/facets/1-0-0/BuildReferencesDatasetFacet.json"
    "#/$defs/BuildReferencesDatasetFacet"
)


def _require_openlineage() -> None:
    try:
        import openlineage.client  # type: ignore[import-not-found,import-untyped]  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "openlineage-python is required for dataset_schema_facet. "
            "Install with: pip install 'openlineage-python>=1.28' "
            "or sync the project's `lineage` dependency group."
        ) from exc


def pipeline_config_facet(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Custom run/job-style metadata bag for pipeline configuration (extension facet)."""
    return {
        _PIPELINE_CONFIG_FACET_KEY: {
            "config": config_dict,
        }
    }


def build_references_dataset_facet(
    *,
    dataset_build_id: str | None = None,
    export_panel_version_id: str | None = None,
    content_hash: str | None = None,
    contract_name: str | None = None,
    manifest_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    payload = {
        "dataset_build_id": dataset_build_id,
        "export_panel_version_id": export_panel_version_id,
        "content_hash": content_hash,
        "contract_name": contract_name,
        "manifest_path": manifest_path,
        "output_path": output_path,
    }
    return {
        _BUILD_REFERENCES_DATASET_FACET_KEY: {
            key: value for key, value in payload.items() if value not in (None, "")
        }
    }


def dataset_schema_facet(
    columns: list[str],
    types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a SchemaDatasetFacet mapping suitable for ``InputDataset`` / ``OutputDataset`` ``facets``."""
    _require_openlineage()
    from openlineage.client.facet_v2 import schema_dataset  # type: ignore[import-not-found,import-untyped]

    types = types or {}
    fields = [
        schema_dataset.SchemaDatasetFacetFields(name=col, type=types.get(col))
        for col in columns
    ]
    facet = schema_dataset.SchemaDatasetFacet(fields=fields)
    return {schema_dataset.SchemaDatasetFacet._get_schema(): facet}
