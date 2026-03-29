import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from dagster import AssetExecutionContext, MetadataValue, asset

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import Pipeline  # noqa: E402

from dagster_pipeline.resources import PipelineConfigResource


@asset(group_name="swing_pipeline")
def feature_matrix(
    context: AssetExecutionContext,
    raw_panel: Dict[str, Any],
    pipeline_config: PipelineConfigResource,
) -> Dict[str, Any]:
    """Build feature matrix via `Pipeline.build_feature_matrix`."""
    config = pipeline_config.to_pipeline_config()
    panel: pd.DataFrame = raw_panel["panel"]
    context.log.info(
        "Building feature matrix: panel rows=%s tickers=%s",
        len(panel),
        panel["ticker"].nunique(),
    )
    enriched, features = Pipeline.build_feature_matrix(panel, config)
    context.log.info("Feature matrix ready: rows=%s n_features=%s", len(enriched), len(features))
    context.add_output_metadata(
        {
            "rows": MetadataValue.int(len(enriched)),
            "n_features": MetadataValue.int(len(features)),
        }
    )
    return {"dataframe": enriched, "features": features}
