"""MLflow Model Registry helpers (register, alias, champion lookup)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import mlflow
from mlflow.entities import ModelVersion
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient


def register_model_candidate(
    model_name: str,
    run_id: str,
    artifact_path: str,
    tags: Dict[str, str],
) -> ModelVersion:
    """Register an artifact from a run as a new model version; apply ``tags`` to that version."""
    source = f"runs:/{run_id}/{artifact_path.strip('/')}"
    mv = mlflow.register_model(source, model_name)

    client = MlflowClient()
    version = int(mv.version)
    for k, v in tags.items():
        client.set_model_version_tag(model_name, str(version), k, v)
    return client.get_model_version(model_name, str(version))


def promote_model(model_name: str, version: int, alias: str) -> None:
    """Assign a registry alias (e.g. ``champion`` / ``challenger``) to a model version."""
    MlflowClient().set_registered_model_alias(model_name, alias, str(version))


def get_champion(model_name: str) -> Optional[Dict[str, Any]]:
    """Return champion model metadata for ``model_name``, or ``None`` if alias is missing."""
    client = MlflowClient()
    try:
        mv = client.get_model_version_by_alias(model_name, "champion")
    except MlflowException:
        return None
    return {
        "name": mv.name,
        "version": int(mv.version),
        "run_id": mv.run_id,
        "source": mv.source,
        "status": mv.status,
        "creation_timestamp": mv.creation_timestamp,
        "last_updated_timestamp": mv.last_updated_timestamp,
    }
