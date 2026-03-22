from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from Pipeline import (
    FEATURE_VALIDATION_REPORT_COLUMNS,
    MODEL_COMPARISON_REPORT_COLUMNS,
    PipelineConfig,
    apply_empirical_probability_map,
    build_feature_registry,
    build_feature_validation_report,
    build_model_comparison_report,
    compute_daily_return_diagnostics,
    feature_validation_for_fold,
    label_long_events,
    moving_block_bootstrap_white_reality_check,
    summarize_stitched_policy_daily,
)


pytestmark = pytest.mark.helper


def test_compute_daily_return_diagnostics_uses_phase1_lag_rule() -> None:
    returns = [0.001 + (0.0002 if idx % 2 == 0 else -0.0001) for idx in range(81)]
    diagnostics = compute_daily_return_diagnostics(returns)

    assert diagnostics["n_daily_observations"] == len(returns)
    assert diagnostics["adjusted_sharpe_lag"] == min(5, math.floor(len(returns) ** 0.25))
    assert math.isfinite(diagnostics["adjusted_sharpe_daily"])


def test_summarize_stitched_policy_daily_keeps_zero_return_windows() -> None:
    policy_daily = pd.DataFrame(
        {
            "session_date_ny": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "daily_return": [0.02, 0.0, -0.01],
            "active_positions_mean": [1.0, 0.0, 1.0],
            "active_positions_p95": [1.0, 0.0, 1.0],
            "active_positions_max": [1.0, 0.0, 1.0],
            "active_exposure_mean": [0.125, 0.0, 0.125],
            "fold": ["fold_01", "fold_02", "fold_03"],
            "max_concurrent": [8, 8, 8],
            "fold_selected": [1, 0, 1],
            "fold_skip_reason": ["", "wrc_fail", ""],
        }
    )

    stitched, summary = summarize_stitched_policy_daily(
        policy_daily,
        starting_capital=100.0,
        trial_count=108,
    )

    assert stitched["session_date_ny"].tolist() == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert stitched.loc[1, "daily_return"] == 0.0
    assert math.isclose(stitched.loc[1, "equity"], stitched.loc[0, "equity"])
    assert summary["n_daily_observations"] == 3
    assert summary["trial_count_formal"] == 108


def test_summarize_stitched_policy_daily_collapses_duplicate_boundary_days() -> None:
    policy_daily = pd.DataFrame(
        {
            "session_date_ny": ["2024-01-02", "2024-01-02", "2024-01-03"],
            "daily_return": [0.01, 0.02, -0.01],
            "active_positions_mean": [1.0, 2.0, 0.0],
            "active_positions_p95": [1.0, 2.0, 0.0],
            "active_positions_max": [1.0, 2.0, 0.0],
            "active_exposure_mean": [0.125, 0.250, 0.0],
            "fold": ["fold_01", "fold_02", "fold_03"],
            "max_concurrent": [8, 8, 8],
            "fold_selected": [1, 1, 0],
            "fold_skip_reason": ["", "", "wrc_fail"],
            "schema_version": ["2.1.0"] * 3,
            "robustness_method_version": ["phase1_threshold_wrc_nw_v2"] * 3,
            "search_family_definition_version": ["threshold_policy_family_v1"] * 3,
            "implementation_status": ["unit_tested"] * 3,
            "verification_stage_reached": ["unit_tests"] * 3,
            "threshold_search_corrected": [True] * 3,
            "full_pipeline_corrected": [False] * 3,
            "trial_scope_formal": ["threshold_policy_search_only"] * 3,
            "trial_count_formal": [108] * 3,
        }
    )

    stitched, summary = summarize_stitched_policy_daily(
        policy_daily,
        starting_capital=100.0,
        trial_count=108,
    )

    assert stitched["session_date_ny"].tolist() == ["2024-01-02", "2024-01-03"]
    assert math.isclose(stitched.loc[0, "daily_return"], (1.01 * 1.02) - 1.0, rel_tol=1e-9)
    assert summary["n_daily_observations"] == 2


def test_build_feature_validation_report_applies_phase1_thresholds() -> None:
    registry = build_feature_registry(["ret_5"])
    fold_rows = pd.DataFrame(
        [
            {
                "fold": "fold_01",
                "feature": "ret_5",
                "family": "returns_momentum",
                "expected_sign": "positive",
                "feature_validation_status": "ok",
                "positive_fold": 1,
                "regime_positive_count": 2,
                "monotonic_top_minus_bottom_tstat": 2.5,
                "incremental_lift_after_costs": 0.02,
                "ic_mean": 0.04,
                "ic_tstat_hac": 2.6,
            },
            {
                "fold": "fold_02",
                "feature": "ret_5",
                "family": "returns_momentum",
                "expected_sign": "positive",
                "feature_validation_status": "ok",
                "positive_fold": 1,
                "regime_positive_count": 2,
                "monotonic_top_minus_bottom_tstat": 2.2,
                "incremental_lift_after_costs": 0.01,
                "ic_mean": 0.03,
                "ic_tstat_hac": 2.4,
            },
        ]
    )
    daily_rows = pd.DataFrame(
        {
            "feature": ["ret_5"] * 6,
            "spearman_ic": [0.03, 0.05, 0.04, 0.02, 0.03, 0.04],
        }
    )

    report = build_feature_validation_report(fold_rows, daily_rows, registry)

    assert int(report.loc[0, "feature_validation_pass"]) == 1
    assert int(report.loc[0, "feature_validation_preferred"]) == 1


def test_feature_validation_for_fold_returns_insufficient_rows_when_label_return_missing() -> None:
    registry = build_feature_registry(["ret_5"])
    scored = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "timestamp_utc": pd.to_datetime(["2024-01-02", "2024-01-02"], utc=True),
            "ret_5": [0.10, -0.20],
        }
    )

    rows, daily_rows = feature_validation_for_fold(scored, registry, "fold_01")

    ret_5_row = next(row for row in rows if row["feature"] == "ret_5")

    assert len(rows) == len(registry)
    assert ret_5_row["feature_validation_status"] == "insufficient_data"
    assert ret_5_row["feature_validation_pass"] == 0
    assert daily_rows == []


def test_label_long_events_populates_forward_label_return_net() -> None:
    config = PipelineConfig(
        max_horizon_bars=2,
        stop_atr_multiple=1.0,
        target_atr_multiple=2.0,
        slippage_per_fill=0.0,
        overnight_brokerage=0.0,
    )
    panel = pd.DataFrame(
        {
            "ticker": ["AAA"] * 4,
            "timestamp_utc": pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], utc=True
            ),
            "open": [99.0, 100.0, 101.0, 102.0],
            "high": [100.0, 111.0, 103.0, 104.0],
            "low": [98.0, 99.0, 100.0, 101.0],
            "close": [99.5, 110.0, 102.0, 103.0],
            "atr_14": [5.0, 5.0, 5.0, 5.0],
            "is_incomplete_session": [False, False, False, False],
        }
    )

    labeled = label_long_events(panel, config)

    assert "forward_label_return_net" in labeled.columns
    assert math.isclose(float(labeled.iloc[0]["forward_label_return_net"]), 0.10, rel_tol=1e-9)
    assert int(labeled.iloc[0]["long_win"]) == 1


def test_build_feature_validation_report_preserves_schema_when_empty() -> None:
    registry = build_feature_registry(["ret_5"])

    report = build_feature_validation_report(pd.DataFrame(), pd.DataFrame(), registry)

    assert report.empty
    assert list(report.columns) == list(FEATURE_VALIDATION_REPORT_COLUMNS)


def test_build_model_comparison_report_only_promotes_incumbent_on_baseline_beat() -> None:
    rows = pd.DataFrame(
        [
            {"fold": "fold_01", "model_name": "baseline_linear", "fold_selected": 1, "adjusted_oos_sharpe": 0.8, "net_oos_spread_after_costs": 0.1, "profit_factor": 1.2, "calmar": 0.5, "max_drawdown": 0.2, "turnover_notional_to_equity": 0.3, "capacity_drag_fraction_of_gross_alpha": 0.05, "n_trades": 10},
            {"fold": "fold_02", "model_name": "baseline_equal_weight_rank_blend", "fold_selected": 1, "adjusted_oos_sharpe": 0.7, "net_oos_spread_after_costs": 0.1, "profit_factor": 1.1, "calmar": 0.4, "max_drawdown": 0.2, "turnover_notional_to_equity": 0.25, "capacity_drag_fraction_of_gross_alpha": 0.05, "n_trades": 10},
            {"fold": "fold_01", "model_name": "incumbent_ml", "fold_selected": 1, "adjusted_oos_sharpe": 1.0, "net_oos_spread_after_costs": 0.2, "profit_factor": 1.3, "calmar": 0.6, "max_drawdown": 0.18, "turnover_notional_to_equity": 0.2, "capacity_drag_fraction_of_gross_alpha": 0.04, "n_trades": 10},
            {"fold": "fold_02", "model_name": "incumbent_ml", "fold_selected": 1, "adjusted_oos_sharpe": 0.9, "net_oos_spread_after_costs": 0.2, "profit_factor": 1.25, "calmar": 0.55, "max_drawdown": 0.18, "turnover_notional_to_equity": 0.2, "capacity_drag_fraction_of_gross_alpha": 0.04, "n_trades": 10},
        ]
    )

    report = build_model_comparison_report(rows)
    incumbent = report.loc[report["model_name"] == "incumbent_ml"].iloc[0]

    assert int(incumbent["model_comparison_pass"]) == 1


def test_build_model_comparison_report_preserves_schema_when_empty() -> None:
    report = build_model_comparison_report(pd.DataFrame())

    assert report.empty
    assert list(report.columns) == list(MODEL_COMPARISON_REPORT_COLUMNS)


def test_apply_empirical_probability_map_falls_back_when_support_is_thin() -> None:
    config = PipelineConfig()
    reference = pd.DataFrame(
        {
            "p_cal": [0.40, 0.45, 0.50, 0.55] * 20,
            "long_win": [0, 0, 1, 1] * 20,
            "cost_est_r": [0.05] * 80,
        }
    )
    target = pd.DataFrame({"p_cal": [0.41, 0.59], "cost_est_r": [0.05, 0.05]})

    ref_scored, tgt_scored, meta = apply_empirical_probability_map(reference, target, config)

    assert meta["empirical_prob_map_status"] == "deterministic_simple_rank_fallback"
    assert meta["ranking_map_fallback_usage_fraction"] == 1.0
    assert bool(meta["ranking_map_guardrails_pass"]) is False
    assert meta["ranking_map_guardrail_failure_reasons"] == "fallback_usage_fraction_exceeds_max"
    assert bool(meta["ranking_map_stability_pass"]) is False
    assert "p_empirical" in ref_scored.columns
    assert "ev_empirical_r" in tgt_scored.columns


def test_apply_empirical_probability_map_promotes_isotonic_when_support_is_sufficient() -> None:
    config = PipelineConfig()
    scores = pd.Series([0.05 + i * (0.90 / 399) for i in range(400)], dtype=float)
    reference = pd.DataFrame(
        {
            "p_cal": scores,
            "long_win": (scores >= 0.55).astype(int),
            "cost_est_r": [0.05] * 400,
        }
    )
    target = pd.DataFrame({"p_cal": [0.15, 0.45, 0.85], "cost_est_r": [0.05, 0.05, 0.05]})

    _, tgt_scored, meta = apply_empirical_probability_map(reference, target, config)

    assert meta["empirical_prob_map_status"] == "isotonic"
    assert meta["ranking_map_fallback_usage_fraction"] == 0.0
    assert bool(meta["ranking_map_guardrails_pass"]) is True
    assert meta["ranking_map_guardrail_failure_reasons"] == "ok"
    assert bool(meta["ranking_map_stability_pass"]) is True
    assert len(json.loads(meta["ranking_map_bucket_samples"])) == config.empirical_prob_map_buckets
    assert (tgt_scored["p_empirical"].astype(float).diff().fillna(0.0) >= -1e-9).all()


def test_apply_empirical_probability_map_measures_adjacent_fold_spearman() -> None:
    config = PipelineConfig()
    scores = pd.Series([0.05 + i * (0.90 / 399) for i in range(400)], dtype=float)
    reference = pd.DataFrame(
        {
            "p_cal": scores,
            "long_win": (scores >= 0.55).astype(int),
            "cost_est_r": [0.05] * 400,
        }
    )
    target = pd.DataFrame({"p_cal": [0.15, 0.45, 0.85], "cost_est_r": [0.05, 0.05, 0.05]})
    previous_bucket_positive_rates = [float(idx) for idx in range(config.empirical_prob_map_buckets)]

    _, _, meta = apply_empirical_probability_map(
        reference,
        target,
        config,
        previous_bucket_positive_rates=previous_bucket_positive_rates,
    )

    assert bool(meta["ranking_map_adjacent_fold_spearman_evaluable"]) is True
    assert float(meta["ranking_map_adjacent_fold_spearman"]) >= config.empirical_prob_map_min_adjacent_fold_spearman
    assert bool(meta["ranking_map_guardrails_pass"]) is True


def test_apply_empirical_probability_map_blocks_adjacent_fold_spearman_breach() -> None:
    config = PipelineConfig()
    scores = pd.Series([0.05 + i * (0.90 / 399) for i in range(400)], dtype=float)
    reference = pd.DataFrame(
        {
            "p_cal": scores,
            "long_win": (scores >= 0.55).astype(int),
            "cost_est_r": [0.05] * 400,
        }
    )
    target = pd.DataFrame({"p_cal": [0.15, 0.45, 0.85], "cost_est_r": [0.05, 0.05, 0.05]})
    previous_bucket_positive_rates = [float(config.empirical_prob_map_buckets - idx) for idx in range(config.empirical_prob_map_buckets)]

    _, _, meta = apply_empirical_probability_map(
        reference,
        target,
        config,
        previous_bucket_positive_rates=previous_bucket_positive_rates,
    )

    assert bool(meta["ranking_map_adjacent_fold_spearman_evaluable"]) is True
    assert float(meta["ranking_map_adjacent_fold_spearman"]) < config.empirical_prob_map_min_adjacent_fold_spearman
    assert bool(meta["ranking_map_guardrails_pass"]) is False
    assert "adjacent_fold_spearman_below_min" in str(meta["ranking_map_guardrail_failure_reasons"])


def test_moving_block_bootstrap_white_reality_check_returns_probability() -> None:
    matrix = pd.DataFrame(
        {
            "a": [0.01, 0.02, -0.01, 0.015, 0.005, 0.01],
            "b": [0.0, 0.005, -0.002, 0.004, 0.003, 0.002],
        }
    ).to_numpy()

    result = moving_block_bootstrap_white_reality_check(
        matrix,
        block_length=2,
        bootstrap_reps=50,
        random_seed=42,
    )

    assert 0.0 <= result["wrc_pvalue"] <= 1.0
    assert result["bootstrap_reps"] == 50
