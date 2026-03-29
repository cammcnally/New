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
def raw_panel(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfigResource,
) -> Dict[str, Any]:
    """Load panel CSV and run `Pipeline.verify_panel`."""
    config = pipeline_config.to_pipeline_config()
    context.log.info("Loading panel from %s", config.input_panel_csv)
    df = Pipeline.load_panel(config)
    verification = Pipeline.verify_panel(df)
    context.log.info(
        "Panel verified: rows=%s tickers=%s",
        verification.get("rows"),
        len(verification.get("tickers", []) or []),
    )
    context.add_output_metadata(
        {
            "rows": MetadataValue.int(int(verification.get("rows", 0) or 0)),
            "n_tickers": MetadataValue.int(len(verification.get("tickers", []) or [])),
            "duplicate_ticker_timestamp_rows": MetadataValue.int(
                int(verification.get("duplicate_ticker_timestamp_rows", 0) or 0)
            ),
        }
    )
    return {"panel": df, "verification": dict(verification)}
