import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd
from dagster import AssetExecutionContext, MetadataValue, asset

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import Pipeline  # noqa: E402

from dagster_pipeline.resources import PipelineConfigResource


@asset(group_name="swing_pipeline")
def labeled_dataset(
    context: AssetExecutionContext,
    feature_matrix: Dict[str, Any],
    pipeline_config: PipelineConfigResource,
) -> pd.DataFrame:
    """`Pipeline.label_long_events` then drop incomplete sessions (same filter as `run_pipeline`)."""
    config = pipeline_config.to_pipeline_config()
    enriched: pd.DataFrame = feature_matrix["dataframe"]
    context.log.info("Labeling long events on %s rows...", len(enriched))
    labeled = Pipeline.label_long_events(enriched, config)
    before = len(labeled)
    labeled = labeled[~labeled["is_incomplete_session"].astype(bool)].copy()
    context.log.info("Incomplete-session filter: %s / %s rows retained", len(labeled), before)
    context.add_output_metadata(
        {
            "rows": MetadataValue.int(len(labeled)),
            "rows_before_session_filter": MetadataValue.int(before),
        }
    )
    return labeled
