from __future__ import annotations

from typing import Any

_PIPELINE_CONFIG_FACET_KEY = (
    "https://swing-pipeline.local/spec/facets/1-0-0/PipelineConfigRunFacet.json"
    "#/$defs/PipelineConfigRunFacet"
)


def _require_openlineage() -> None:
    try:
        import openlineage.client  # noqa: F401
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


def dataset_schema_facet(
    columns: list[str],
    types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a SchemaDatasetFacet mapping suitable for ``InputDataset`` / ``OutputDataset`` ``facets``."""
    _require_openlineage()
    from openlineage.client.facet_v2 import schema_dataset

    types = types or {}
    fields = [
        schema_dataset.SchemaDatasetFacetFields(name=col, type=types.get(col))
        for col in columns
    ]
    facet = schema_dataset.SchemaDatasetFacet(fields=fields)
    return {schema_dataset.SchemaDatasetFacet._get_schema(): facet}
