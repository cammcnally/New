import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import Pipeline  # noqa: E402

from dagster_pipeline.resources import PipelineConfigResource


@asset(group_name="swing_pipeline")
def pipeline_report(
    context: AssetExecutionContext,
    raw_panel: Dict[str, Any],
    feature_matrix: Dict[str, Any],
    fold_results: List[Dict[str, Any]],
    evaluation_results: Dict[str, Any],
    pipeline_config: PipelineConfigResource,
) -> MaterializeResult:
    """Write `Pipeline.write_markdown_report` using upstream asset outputs."""
    config = pipeline_config.to_pipeline_config()
    verification = dict(raw_panel["verification"])
    features: List[str] = list(feature_matrix["features"])
    fold_metrics: pd.DataFrame = evaluation_results["fold_metrics"]
    overall_summary: Dict[str, Any] = dict(evaluation_results["overall_summary"])

    imp_pieces: List[pd.DataFrame] = []
    for r in fold_results:
        fi = r.get("full_imp")
        if isinstance(fi, pd.DataFrame) and not fi.empty:
            imp_pieces.append(fi)
    feature_importance = pd.concat(imp_pieces, ignore_index=True) if imp_pieces else pd.DataFrame()

    output_root = Path(config.output_dir)
    paths = Pipeline.build_output_paths(output_root)
    report_path = paths.reports_dir / "final_report.md"

    context.log.info("Writing markdown report to %s", report_path)
    written = Pipeline.write_markdown_report(
        report_path,
        output_root,
        config,
        verification,
        features,
        fold_metrics,
        overall_summary,
        feature_importance,
    )
    context.log.info("Report written: %s", written)
    return MaterializeResult(
        metadata={
            "report_path": MetadataValue.path(str(written)),
            "n_fold_metric_rows": MetadataValue.int(len(fold_metrics)),
        }
    )
