import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from dagster import AssetExecutionContext, MetadataValue, asset

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import Pipeline  # noqa: E402

from dagster_pipeline.resources import PipelineConfigResource


def _fold_metrics_rows(fold_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in fold_results:
        row: Dict[str, Any] = {
            "fold": r["fold_name"],
            "train_rows": len(r["train_df"]),
            "test_rows": len(r["test_df"]),
        }
        for k, v in r["train_diag"].items():
            row[f"train_{k}"] = v
        for k, v in r["test_diag"].items():
            row[f"test_{k}"] = v
        row.update(r["bench_diag"])
        row.update(r["ranking_map_row"])
        rows.append(row)
    return rows


@asset(group_name="swing_pipeline")
def evaluation_results(
    context: AssetExecutionContext,
    fold_results: List[Dict[str, Any]],
    pipeline_config: PipelineConfigResource,
) -> Dict[str, Any]:
    """Aggregate fold-level diagnostics and ranking-map guardrails via `Pipeline.summarize_ranking_map_guardrails`."""
    config = pipeline_config.to_pipeline_config()
    rows = _fold_metrics_rows(fold_results)
    fold_metrics_df = pd.DataFrame(rows) if rows else pd.DataFrame()
    guardrails = Pipeline.summarize_ranking_map_guardrails(fold_metrics_df, config)

    overall: Dict[str, Any] = {
        "n_folds_completed": len(fold_results),
        "schema_version": Pipeline.SCHEMA_VERSION,
        "robustness_method_version": Pipeline.ROBUSTNESS_METHOD_VERSION,
        "search_family_definition_version": Pipeline.SEARCH_FAMILY_DEFINITION_VERSION,
        "threshold_search_corrected": Pipeline.THRESHOLD_SEARCH_CORRECTED,
        "full_pipeline_corrected": Pipeline.FULL_PIPELINE_CORRECTED,
        "trial_scope_formal": Pipeline.TRIAL_SCOPE_FORMAL,
        "trial_count_formal": int(Pipeline.threshold_policy_trial_count(config)),
        "implementation_status": config.implementation_status,
        "verification_stage_reached": config.verification_stage_reached,
        "scorecard_label": Pipeline.SCORECARD_LABEL,
        "scorecard_archetype": Pipeline.SCORECARD_ARCHETYPE,
    }
    if len(fold_metrics_df) and "test_pr_auc" in fold_metrics_df.columns:
        overall["mean_test_pr_auc"] = float(np.nanmean(fold_metrics_df["test_pr_auc"].astype(float)))
    if len(fold_metrics_df) and "test_roc_auc" in fold_metrics_df.columns:
        overall["mean_test_roc_auc"] = float(np.nanmean(fold_metrics_df["test_roc_auc"].astype(float)))
    overall.update(guardrails)

    context.log.info(
        "Evaluation summary: folds=%s ranking_map_guardrails_pass=%s",
        overall["n_folds_completed"],
        overall.get("ranking_map_guardrails_pass"),
    )
    context.add_output_metadata(
        {
            "n_folds_completed": MetadataValue.int(int(overall["n_folds_completed"])),
            "ranking_map_guardrails_pass": MetadataValue.bool(
                bool(overall.get("ranking_map_guardrails_pass", False))
            ),
        }
    )
    return {
        "fold_metrics": fold_metrics_df,
        "overall_summary": overall,
    }
