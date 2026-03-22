from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import Pipeline as pipeline_module
from Pipeline import (
    PipelineConfig,
    _require_supported_python_version,
    build_resume_fingerprint,
    choose_thresholds,
    research_score,
    run_optuna_inner,
    validate_cost_model,
)


pytestmark = pytest.mark.regression
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _minimal_holdout_frame() -> pd.DataFrame:
    timestamps = pd.to_datetime(
        [
            "2024-01-02T15:00:00Z",
            "2024-01-03T15:00:00Z",
            "2024-01-04T15:00:00Z",
            "2024-01-05T15:00:00Z",
        ],
        utc=True,
    )
    return pd.DataFrame(
        {
            "ticker": ["AAA", "AAA", "AAA", "AAA"],
            "timestamp_utc": timestamps,
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [10.2, 10.2, 10.2, 10.2],
            "low": [9.8, 9.8, 9.8, 9.8],
            "close": [10.0, 10.0, 10.0, 10.0],
            "volume": [1000.0, 1000.0, 1000.0, 1000.0],
            "atr_14": [1.0, 1.0, 1.0, 1.0],
            "p_cal": [0.10, 0.10, 0.10, 0.10],
            "entry_open_next": [10.0, 10.0, 10.0, 10.0],
            "cost_est_r": [0.05, 0.05, 0.05, 0.05],
            "rel_volume_20": [1.0, 1.0, 1.0, 1.0],
        }
    )


def test_resume_fingerprint_ignores_output_dir_but_detects_core_mismatch() -> None:
    baseline = PipelineConfig()
    same_semantics = PipelineConfig(output_dir="other_outputs", resume=True)
    changed_semantics = PipelineConfig(threshold_holdout_months=baseline.threshold_holdout_months + 1)

    assert build_resume_fingerprint(baseline) == build_resume_fingerprint(same_semantics)
    assert build_resume_fingerprint(baseline) != build_resume_fingerprint(changed_semantics)


def test_choose_thresholds_marks_insufficient_data_as_not_selected() -> None:
    config = PipelineConfig()
    best_bundle, candidate_df, wrc_summary = choose_thresholds(
        _minimal_holdout_frame(),
        config,
        "fold_01",
        max_concurrent=8,
    )

    assert best_bundle["p_min"] in config.p_min_grid
    assert len(candidate_df) == 108
    assert wrc_summary["trial_count_formal"] == 108
    assert wrc_summary["wrc_status"] == "insufficient_data"
    assert wrc_summary["wrc_pass"] == 0
    assert int(wrc_summary["wrc_pass"] == 1) == 0


def test_research_score_ignores_occupancy_metrics() -> None:
    base_metrics = {
        "n_trades": 100,
        "profit_factor": 1.5,
        "expectancy_r": 0.2,
        "calmar": 1.2,
        "mdd": 0.1,
        "cagr": 0.25,
        "churn": 0.08,
    }
    fold_expectancies = [0.15, 0.18, 0.20]

    score_without_occupancy, meta_without_occupancy = research_score(
        {
            **base_metrics,
            "avg_active_positions_daily": 0.0,
            "at_cap_day_fraction": 0.0,
            "avg_active_exposure_daily": 0.0,
        },
        fold_expectancies,
        top_ticker_share_abs=0.10,
    )
    score_with_extreme_occupancy, meta_with_extreme_occupancy = research_score(
        {
            **base_metrics,
            "avg_active_positions_daily": 8.0,
            "at_cap_day_fraction": 1.0,
            "avg_active_exposure_daily": 1.0,
        },
        fold_expectancies,
        top_ticker_share_abs=0.10,
    )

    assert score_without_occupancy == score_with_extreme_occupancy
    assert meta_without_occupancy == meta_with_extreme_occupancy


def test_promotion_source_blocks_non_positive_dsr_and_excludes_occupancy_terms() -> None:
    source = (PROJECT_ROOT / "Pipeline.py").read_text(encoding="utf-8")

    assert "deflated_sharpe_non_positive" in source
    assert "deflated_sharpe_value <= 0" in source

    block_start = source.index("robustness_failures: List[str] = []")
    block_end = source.index('overall_metrics["promotion_pass"]', block_start)
    promotion_block = source[block_start:block_end]

    for forbidden_term in (
        "occupancy",
        "avg_active_positions",
        "at_cap_day_fraction",
        "avg_active_exposure_daily",
        "flat_day_fraction",
    ):
        assert forbidden_term not in promotion_block


def test_cost_model_schema_rejects_missing_required_fields() -> None:
    broken = PipelineConfig(spread_source="")
    ok, missing, _ = validate_cost_model(broken)

    assert ok is False
    assert "spread_source" in missing


def test_pipeline_python_version_gate_enforces_supported_range() -> None:
    _require_supported_python_version((3, 12, 10))
    _require_supported_python_version((3, 12, 12))
    with pytest.raises(SystemExit):
        _require_supported_python_version((3, 14, 2))


def test_pipeline_source_removes_fake_cache_and_legacy_resume_surfaces() -> None:
    source = (PROJECT_ROOT / "Pipeline.py").read_text(encoding="utf-8")

    for forbidden_term in (
        "cache_enabled",
        "--cache_enabled",
        "_resolve_artifact_path",
        "legacy_resume_path",
        'output_dir / "resume_state.json"',
        "max_capacity_drag_fraction_allocation",
        "atr_length",
        "long_only_primary_book",
        "derive_implementation_status",
    ):
        assert forbidden_term not in source

    for required_term in (
        "config.empirical_prob_map_max_fallback_usage_fraction",
        "config.empirical_prob_map_min_adjacent_fold_spearman",
        "ranking_map_guardrails_pass",
        'resume_path = paths.state_dir / "resume_state.json"',
        'repo_root / "docs" / "phase1-research-spec.md"',
    ):
        assert required_term in source


def test_run_optuna_inner_stops_at_phase1_wall_clock_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    train_df = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(["2024-01-02T15:00:00Z", "2024-01-03T15:00:00Z"], utc=True),
            "long_win": [0, 1],
        }
    )
    config = PipelineConfig(optuna_n_trials=20)

    clock_values = iter([0.0, 1201.0, 1201.0, 2000.0, 3201.0, 3201.0, 4000.0, 5201.0, 5201.0])
    monkeypatch.setattr(pipeline_module.time, "monotonic", lambda: next(clock_values))
    monkeypatch.setattr(pipeline_module, "OPTUNA_AVAILABLE", True)
    monkeypatch.setattr(pipeline_module, "purged_splits", lambda *_args, **_kwargs: [])

    class FakeStudy:
        def __init__(self) -> None:
            self.best_params = {"n_estimators": 150}
            self.trials = [SimpleNamespace(number=0)]
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        def optimize(self, _objective, *, callbacks, **_kwargs) -> None:
            for callback in callbacks:
                callback(self, SimpleNamespace(number=0))

    class FakeSampler:
        def __init__(self, seed: int) -> None:
            self.seed = seed

    fake_optuna = SimpleNamespace(
        samplers=SimpleNamespace(TPESampler=FakeSampler),
        create_study=lambda **_kwargs: FakeStudy(),
    )
    monkeypatch.setattr(pipeline_module, "optuna", fake_optuna)

    best_params, summary = run_optuna_inner(train_df, config, features=("feature_a",))

    assert set(best_params) == {"RF", "ET", "XGB"}
    for model_name in ("RF", "ET", "XGB"):
        assert best_params[model_name] == {"n_estimators": 150}
        assert summary[model_name]["wall_clock_cap_seconds"] == 20 * 60
        assert summary[model_name]["stopped_for_wall_clock"] is True
        assert summary[model_name]["elapsed_seconds"] >= 20 * 60
