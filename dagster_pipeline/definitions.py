"""Dagster `Definitions` entry point for the swing pipeline asset graph."""

import sys
from pathlib import Path

from dagster import AssetCheckResult, Definitions, MaterializeResult

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dagster_pipeline.assets.evaluation import evaluation_results
from dagster_pipeline.assets.features import feature_matrix
from dagster_pipeline.assets.ingestion import raw_panel
from dagster_pipeline.assets.labeling import labeled_dataset
from dagster_pipeline.assets.reports import pipeline_report
from dagster_pipeline.assets.training import fold_results
from dagster_pipeline.resources import PipelineConfigResource

defs = Definitions(
    assets=[
        raw_panel,
        feature_matrix,
        labeled_dataset,
        fold_results,
        evaluation_results,
        pipeline_report,
    ],
    resources={"pipeline_config": PipelineConfigResource()},
)

# Surfaces requested for Dagster tooling / future asset checks.
__all__ = ["defs", "MaterializeResult", "AssetCheckResult"]
