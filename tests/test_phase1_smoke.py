from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.phase1_sanity_check import (
    REQUIRED_FEATURE_VALIDATION_COLUMNS,
    REQUIRED_FOLD_COLUMNS,
    REQUIRED_MODEL_COMPARISON_COLUMNS,
    REQUIRED_OVERALL_KEYS,
    REQUIRED_POLICY_DAILY_COLUMNS,
    REQUIRED_POSITION_RANKING_COLUMNS,
    REQUIRED_REPORT_SECTIONS,
    REQUIRED_SCORECARD_COLUMNS,
    REQUIRED_STRATEGY_KEYS,
    REQUIRED_THRESHOLD_COLUMNS,
    main,
)


pytestmark = pytest.mark.smoke


def _common_phase1_payload(*, trial_count: int = 108) -> dict[str, object]:
    return {
        "schema_version": "2.1.0",
        "robustness_method_version": "phase1_threshold_wrc_nw_v2",
        "search_family_definition_version": "threshold_policy_family_v1",
        "implementation_status": "unit_tested",
        "verification_stage_reached": "unit_tests",
        "threshold_search_corrected": True,
        "full_pipeline_corrected": False,
        "trial_scope_formal": "threshold_policy_search_only",
        "trial_count_formal": trial_count,
    }


def _write_csv(path: Path, header: tuple[str, ...], *, trial_count: int = 108) -> None:
    row = {column: "ok" for column in header}
    row.update(
        {
            "wrc_status": "pass",
            "wrc_pvalue": "0.05",
            "fold_selected": "1",
            "fold_skip_reason": "",
            "adjusted_sharpe_daily": "1.0",
            "ranking_map_guardrails_pass": "True",
            "ranking_map_guardrails_pass_threshold_holdout": "True",
            "ranking_map_guardrails_pass_test": "True",
            "ranking_map_guardrail_failure_reasons": "",
            "ranking_map_guardrail_failure_reasons_threshold_holdout": "ok",
            "ranking_map_guardrail_failure_reasons_test": "ok",
            "ranking_map_adjacent_fold_spearman_evaluable_threshold_holdout": "True",
            "ranking_map_adjacent_fold_spearman_evaluable_test": "True",
            "ranking_map_fallback_usage_fraction_threshold_holdout": "0.0",
            "ranking_map_fallback_usage_fraction_test": "0.0",
            "ranking_map_adjacent_fold_spearman_threshold_holdout": "0.9",
            "ranking_map_adjacent_fold_spearman_test": "0.9",
            "ranking_map_max_fallback_usage_fraction_allowed": "0.25",
            "ranking_map_min_adjacent_fold_spearman_allowed": "0.7",
            "ranking_map_bucket_positive_rates_threshold_holdout": "[0.1,0.2,0.3]",
            "ranking_map_bucket_positive_rates_test": "[0.1,0.2,0.3]",
            "promotion_pass": "True",
            "feature_validation_pass": "True",
            "model_comparison_pass": "True",
            "evidence_hierarchy_pass": "True",
            "research_viable": "True",
            "live_pilot_viable": "False",
            "allocation_ready": "False",
            "deflated_sharpe_daily": "0.5",
            **{key: str(value) for key, value in _common_phase1_payload(trial_count=trial_count).items()},
        }
    )
    path.write_text(
        ",".join(header) + "\n" + ",".join(str(row[column]) for column in header) + "\n",
        encoding="utf-8",
    )


def _json_payload(required_keys: tuple[str, ...], *, trial_count: int = 108) -> dict[str, object]:
    payload = {key: "ok" for key in required_keys}
    payload.update(_common_phase1_payload(trial_count=trial_count))
    payload.update(
        {
            "deflated_sharpe_daily": 0.5,
            "ranking_map_guardrails_pass": True,
            "ranking_map_guardrail_failure_reasons": "",
            "ranking_map_max_fallback_usage_fraction_allowed": 0.25,
            "ranking_map_min_adjacent_fold_spearman_allowed": 0.70,
            "ranking_map_fallback_usage_fraction_observed_max_threshold_holdout": 0.0,
            "ranking_map_fallback_usage_fraction_observed_max_test": 0.0,
            "ranking_map_adjacent_fold_spearman_observed_min_threshold_holdout": 0.85,
            "ranking_map_adjacent_fold_spearman_observed_min_test": 0.85,
            "promotion_pass": True,
            "feature_validation_pass": True,
            "model_comparison_pass": True,
            "research_viable": True,
            "live_pilot_viable": False,
            "allocation_ready": False,
            "stitched_daily_total_return": 0.1,
            "stitched_daily_mdd": 0.05,
            "stitched_daily_calmar": 1.5,
        }
    )
    return payload


def _write_artifacts(root: Path, *, trial_count: int = 108) -> None:
    metrics_dir = root / "02_metrics"
    features_dir = root / "03_features"
    strategies_dir = root / "04_strategies"
    reports_dir = root / "05_reports"
    state_dir = root / "06_state"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)
    strategies_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    (metrics_dir / "overall_metrics.json").write_text(
        json.dumps(_json_payload(REQUIRED_OVERALL_KEYS, trial_count=trial_count)),
        encoding="utf-8",
    )
    _write_csv(metrics_dir / "fold_metrics.csv", REQUIRED_FOLD_COLUMNS, trial_count=trial_count)
    _write_csv(
        metrics_dir / "threshold_candidate_diagnostics.csv",
        REQUIRED_THRESHOLD_COLUMNS,
        trial_count=trial_count,
    )
    _write_csv(metrics_dir / "policy_daily_returns.csv", REQUIRED_POLICY_DAILY_COLUMNS, trial_count=trial_count)
    _write_csv(
        features_dir / "feature_validation_report.csv",
        REQUIRED_FEATURE_VALIDATION_COLUMNS,
        trial_count=trial_count,
    )
    (strategies_dir / "best_strategy_summary.json").write_text(
        json.dumps(_json_payload(REQUIRED_STRATEGY_KEYS, trial_count=trial_count)),
        encoding="utf-8",
    )
    _write_csv(
        strategies_dir / "model_comparison_report.csv",
        REQUIRED_MODEL_COMPARISON_COLUMNS,
        trial_count=trial_count,
    )
    _write_csv(
        strategies_dir / "position_ranking_audit.csv",
        REQUIRED_POSITION_RANKING_COLUMNS,
        trial_count=trial_count,
    )
    _write_csv(
        strategies_dir / "strategy_scorecards.csv",
        REQUIRED_SCORECARD_COLUMNS,
        trial_count=trial_count,
    )
    (state_dir / "resume_state.json").write_text(
        json.dumps(
            {
                **_common_phase1_payload(trial_count=trial_count),
                "resume_fingerprint": {"ok": True},
                "last_completed_fold": 1,
                "completed_fold_names": ["fold_01"],
            }
        ),
        encoding="utf-8",
    )
    (reports_dir / "final_report.md").write_text(
        "\n\n".join(f"{section}\ncontent" for section in REQUIRED_REPORT_SECTIONS),
        encoding="utf-8",
    )


def test_phase1_sanity_check_passes_on_minimal_artifact_tree(tmp_path: Path) -> None:
    _write_artifacts(tmp_path)

    assert main(["--output_dir", str(tmp_path)]) == 0


def test_phase1_sanity_check_fails_on_trial_count_mismatch(tmp_path: Path) -> None:
    _write_artifacts(tmp_path, trial_count=99)

    assert main(["--output_dir", str(tmp_path)]) == 1
