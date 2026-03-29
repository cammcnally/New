import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import numpy as np
import pandas as pd
from dagster import AssetExecutionContext, MetadataValue, asset

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import Pipeline  # noqa: E402
from Pipeline import PipelineConfig  # noqa: E402

from dagster_pipeline.resources import PipelineConfigResource


def _model_ready_frame(
    labeled: pd.DataFrame,
    features: List[str],
    config: PipelineConfig,
) -> pd.DataFrame:
    """Match `run_pipeline` model-ready filtering (missing-feature fraction gate)."""
    df = labeled.copy()
    if features:
        present = df[features].count(axis=1)
        df["missing_feature_fraction"] = 1.0 - (present / float(len(features)))
    else:
        df["missing_feature_fraction"] = np.nan
    return df[df["missing_feature_fraction"] <= config.max_missing_feature_fraction].copy()


@asset(group_name="swing_pipeline")
def fold_results(
    context: AssetExecutionContext,
    labeled_dataset: pd.DataFrame,
    feature_matrix: Dict[str, Any],
    pipeline_config: PipelineConfigResource,
) -> List[Dict[str, Any]]:
    """Outer walk-forward folds: `Pipeline.build_outer_folds` + `Pipeline.fit_outer_fold` per fold."""
    config = pipeline_config.to_pipeline_config()
    features: List[str] = list(feature_matrix["features"])
    model_df = _model_ready_frame(labeled_dataset, features, config)
    context.log.info("Model-ready rows=%s (after missing-feature gate)", len(model_df))

    folds = Pipeline.build_outer_folds(model_df, config)
    context.log.info("Outer folds to iterate: %s", len(folds))

    results: List[Dict[str, Any]] = []
    prev_rates: Optional[List[float]] = None

    for fold_num, (_, train_end, test_start, test_end) in enumerate(folds, start=1):
        fold_name = f"fold_{fold_num:02d}"
        train_df = model_df[model_df["timestamp_utc"] < train_end].copy()
        test_df = model_df[
            (model_df["timestamp_utc"] >= test_start) & (model_df["timestamp_utc"] < test_end)
        ].copy()
        if len(train_df) == 0 or len(test_df) == 0:
            context.log.warning("%s: empty train or test; skip", fold_name)
            continue
        train_df = Pipeline.purge_outer_train_boundary(train_df, test_start)
        if len(train_df) == 0:
            context.log.warning("%s: no train rows after outer-boundary purge; skip", fold_name)
            continue
        if len(train_df["long_win"].unique()) < 2 or len(test_df["long_win"].unique()) < 2:
            context.log.warning("%s: need both classes in train/test; skip", fold_name)
            continue
        context.log.info(
            "%s: fitting outer fold | train=%s test=%s",
            fold_name,
            len(train_df),
            len(test_df),
        )
        try:
            train_scored, test_scored, inner_imp, full_imp, calib_stats, empirical_meta = (
                Pipeline.fit_outer_fold(
                    train_df,
                    test_df,
                    features,
                    config,
                    fold_name,
                    previous_bucket_positive_rates=prev_rates,
                )
            )
        except RuntimeError as exc:
            context.log.warning("%s: fit_outer_fold failed: %s", fold_name, exc)
            continue

        train_diag = Pipeline.classification_diagnostics(train_scored["long_win"], train_scored["p_cal"])
        test_diag = Pipeline.classification_diagnostics(test_scored["long_win"], test_scored["p_cal"])
        bench_diag = Pipeline.benchmark_base_rate_metrics(test_scored["long_win"], train_df["long_win"])
        ranking_row = Pipeline._ranking_map_artifact_fields(
            cast(Dict[str, Any], empirical_meta),
            suffix="test",
        )

        results.append(
            {
                "fold_name": fold_name,
                "train_df": train_df,
                "test_df": test_df,
                "train_scored": train_scored,
                "test_scored": test_scored,
                "inner_imp": inner_imp,
                "full_imp": full_imp,
                "calib_stats": calib_stats,
                "empirical_meta": empirical_meta,
                "train_diag": train_diag,
                "test_diag": test_diag,
                "bench_diag": bench_diag,
                "ranking_map_row": ranking_row,
            }
        )
        prev_rates = Pipeline._deserialize_bucket_positive_rates(
            empirical_meta.get("ranking_map_bucket_positive_rates")
        )

    context.add_output_metadata({"n_folds_completed": MetadataValue.int(len(results))})
    return results
