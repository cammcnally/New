"""MLflow tracking helpers for `PipelineConfig` and pipeline metrics."""

from __future__ import annotations

import json
import numbers
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator, Optional

import mlflow

if TYPE_CHECKING:
    from Pipeline import PipelineConfig


def _mlruns_uri() -> str:
    root = Path("mlruns").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root.as_uri()


def _config_param_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _config_to_params(config: "PipelineConfig") -> Dict[str, str]:
    return {k: _config_param_value(v) for k, v in asdict(config).items()}


def _scalar_metric_value(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return float(value)
    return None


@contextmanager
def pipeline_run_context(
    config: "PipelineConfig",
    *,
    extra_tags: Optional[Dict[str, Any]] = None,
    extra_params: Optional[Dict[str, Any]] = None,
) -> Iterator[Any]:
    """Start a tracked run: local ``mlruns/``, experiment ``swing-pipeline``, config params and tags."""
    from Pipeline import SCHEMA_VERSION, build_config_hash

    mlflow.set_tracking_uri(_mlruns_uri())
    mlflow.set_experiment("swing-pipeline")

    cfg_hash = build_config_hash(config)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    tags: Dict[str, str] = {
        "config_hash": cfg_hash,
        "python_version": py_ver,
        "pipeline_version": str(SCHEMA_VERSION),
    }
    if extra_tags:
        tags.update({str(k): _config_param_value(v) for k, v in extra_tags.items() if v is not None})

    with mlflow.start_run(tags=tags) as run:
        mlflow.log_params(_config_to_params(config))
        if extra_params:
            mlflow.log_params(
                {str(k): _config_param_value(v) for k, v in extra_params.items() if v is not None}
            )
        yield run


def log_fold_metrics(fold_name: str, metrics: Dict[str, Any]) -> None:
    """Log per-fold scalars with prefix ``fold.{fold_name}.``."""
    prefix = f"fold.{fold_name}."
    for key, raw in metrics.items():
        v = _scalar_metric_value(raw)
        if v is not None:
            mlflow.log_metric(prefix + str(key), v)
        elif raw is not None:
            mlflow.log_param(prefix + str(key), _config_param_value(raw))


def log_aggregate_metrics(overall: Dict[str, Any]) -> None:
    """Log aggregate scalars as metrics; booleans as 0/1; other values as params when needed."""
    promotion_keys = (
        "promotion_pass",
        "robustness_pass",
        "portfolio_policy_pass",
        "evidence_hierarchy_pass",
        "feature_validation_pass",
        "model_comparison_pass",
        "ranking_map_guardrails_pass",
        "research_viable",
        "live_pilot_viable",
        "allocation_ready",
        "capacity_rule_compliant",
        "sufficient_stitched_oos",
        "chronology_checks_pass",
    )
    metric_keys = (
        "sharpe_daily_raw",
        "adjusted_sharpe_daily",
        "deflated_sharpe_daily",
        "deflated_sharpe_probability",
        "deflated_sharpe_benchmark",
        "stitched_daily_cagr",
        "stitched_daily_mdd",
        "stitched_daily_calmar",
        "stitched_daily_total_return",
        "daily_cagr",
        "daily_mdd",
        "daily_calmar",
        "cagr",
        "mdd",
        "calmar",
        "expectancy_r",
        "n_folds",
        "n_selected_folds",
        "n_skipped_folds",
        "fold_skip_rate",
        "white_rc_pass_rate",
        "research_score",
        "n_daily_observations",
        "churn",
    )

    logged: set[str] = set()
    for key in promotion_keys + metric_keys:
        if key not in overall:
            continue
        raw = overall[key]
        v = _scalar_metric_value(raw)
        if v is not None:
            mlflow.log_metric(key, v)
        else:
            mlflow.log_param(key, _config_param_value(raw))
        logged.add(key)

    for key, raw in overall.items():
        if key in logged:
            continue
        v = _scalar_metric_value(raw)
        if v is not None:
            mlflow.log_metric(key, v)


def log_dataset(name: str, path: str, digest: Optional[str] = None) -> None:
    """Log a dataset input via ``mlflow.data`` (CSV schema via ``from_pandas``; else metadata dataset)."""
    resolved = Path(path).expanduser().resolve()
    src_str = str(resolved)

    if resolved.suffix.lower() == ".csv":
        import pandas as pd
        from mlflow.data import from_pandas

        df = pd.read_csv(resolved, nrows=0)
        dataset = from_pandas(df, source=src_str, name=name, digest=digest)
    else:
        from mlflow.data.dataset_source_registry import resolve_dataset_source
        from mlflow.data.meta_dataset import MetaDataset

        dataset = MetaDataset(source=resolve_dataset_source(src_str), name=name, digest=digest)

    mlflow.log_input(dataset, context="training")


def log_artifact_path(path: str) -> None:
    resolved = Path(path).expanduser().resolve()
    if resolved.exists():
        mlflow.log_artifact(str(resolved))
