from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from Pipeline import (
    FEATURE_VALIDATION_REPORT_COLUMNS,
    MODEL_COMPARISON_REPORT_COLUMNS,
    PipelineConfig,
    compute_benchmark_diagnostics,
    apply_empirical_probability_map,
    build_feature_set_version,
    build_feature_registry,
    build_feature_validation_report,
    load_input_build_metadata,
    load_benchmark_surface_from_metadata,
    require_input_build_metadata,
    build_model_comparison_report,
    compute_daily_return_diagnostics,
    feature_validation_for_fold,
    label_long_events,
    moving_block_bootstrap_white_reality_check,
    run_pipeline_with_optional_lineage,
    summarize_stitched_policy_daily,
)


pytestmark = pytest.mark.helper


def test_load_input_build_metadata_reads_export_manifest_sidecar(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.csv"
    panel_path.write_text("ticker,timestamp_utc,open,high,low,close,volume,is_incomplete_session\n")
    benchmark_surface = tmp_path / "panel_benchmark_surface_daily.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-08"]),
            "spy_ret_1d": [0.01],
            "spy_cumret": [0.01],
        }
    ).to_parquet(benchmark_surface)
    manifest_path = Path(str(panel_path) + ".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_build_id": "dataset-build-1",
                "export_panel_version_id": "export-build-1",
                "contract_name": "export_panel",
                "content_hash": "abc123",
                "side_artifacts": {"benchmark_surface_daily": str(benchmark_surface)},
            }
        ),
        encoding="utf-8",
    )

    metadata = load_input_build_metadata(panel_path)

    assert metadata["dataset_build_id"] == "dataset-build-1"
    assert metadata["export_panel_version_id"] == "export-build-1"
    assert metadata["input_panel_manifest_path"] == str(manifest_path)
    assert metadata["input_panel_manifest_present"] is True
    assert metadata["benchmark_surface_path"] == str(benchmark_surface)
    assert metadata["benchmark_surface_present"] is True


def test_load_benchmark_surface_from_metadata_reads_manifest_advertised_artifact(
    tmp_path: Path,
) -> None:
    benchmark_surface = tmp_path / "benchmark_surface.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-08", "2024-01-09"]),
            "spy_ret_1d": [0.01, 0.02],
            "spy_cumret": [0.01, 0.0302],
            "dff_daily_rate": [0.0001, 0.0001],
        }
    ).to_parquet(benchmark_surface)
    df = load_benchmark_surface_from_metadata(
        {"benchmark_surface_path": str(benchmark_surface)}
    )
    assert df is not None
    assert list(df.columns) == ["date", "spy_ret_1d", "spy_cumret", "dff_daily_rate"]


def test_compute_benchmark_diagnostics_returns_spy_and_dff_metrics() -> None:
    daily_frame = pd.DataFrame(
        {
            "session_date_ny": ["2024-01-08", "2024-01-09", "2024-01-10"],
            "daily_return": [0.015, -0.005, 0.010],
        }
    )
    benchmark_surface = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"]).date,
            "spy_ret_1d": [0.010, -0.010, 0.005],
            "spy_cumret": [0.010, -0.0001, 0.0049],
            "dff_daily_rate": [0.0001, 0.0001, 0.0001],
        }
    )
    metrics = compute_benchmark_diagnostics(daily_frame, benchmark_surface)
    assert metrics["benchmark_surface_present"] == 1.0
    assert metrics["benchmark_obs"] == 3.0
    assert math.isfinite(metrics["tracking_error_vs_spy"])
    assert math.isfinite(metrics["information_ratio_vs_spy"])
    assert math.isfinite(metrics["beta_vs_spy"])
    assert math.isfinite(metrics["correlation_vs_spy"])
    assert math.isfinite(metrics["excess_return_mean_daily_vs_dff"])


def test_require_input_build_metadata_rejects_missing_manifest(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.csv"
    panel_path.write_text("ticker,timestamp_utc,open,high,low,close,volume,is_incomplete_session\n")

    metadata = load_input_build_metadata(panel_path)

    with pytest.raises(RuntimeError, match="Input panel manifest is required"):
        require_input_build_metadata(panel_path, metadata)


def test_run_pipeline_with_optional_lineage_writes_summary_when_lineage_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lineage
    import lineage.facets as lineage_facets
    import Pipeline as pipeline_module

    panel_path = tmp_path / "panel.csv"
    panel_path.write_text("ticker,timestamp_utc,open,high,low,close,volume,is_incomplete_session\n")
    manifest_path = Path(str(panel_path) + ".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_build_id": "dataset-build-1",
                "export_panel_version_id": "export-build-1",
                "contract_name": "export_panel",
                "content_hash": "abc123",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(pipeline_module, "CANONICAL_BASE", tmp_path)

    events: list[tuple[str, object]] = []

    class _FakeEmitter:
        def __init__(self, *, output_dir: str) -> None:
            self.output_dir = output_dir

        def emit_start(self, run_id: str, input_datasets: list[dict[str, object]], config_facet: dict[str, object] | None = None) -> None:
            events.append(("start", {"run_id": run_id, "inputs": input_datasets, "config_facet": config_facet}))

        def emit_complete(self, run_id: str, output_datasets: list[dict[str, object]]) -> None:
            events.append(("complete", {"run_id": run_id, "outputs": output_datasets}))

        def emit_fail(self, run_id: str, error_message: str) -> None:
            events.append(("fail", {"run_id": run_id, "error_message": error_message}))

    monkeypatch.setattr(lineage, "PipelineLineageEmitter", _FakeEmitter)
    monkeypatch.setattr(lineage_facets, "dataset_schema_facet", lambda columns, types=None: {"schema": {"columns": columns, "types": types or {}}})
    monkeypatch.setattr(lineage_facets, "pipeline_config_facet", lambda config_dict: {"config": config_dict})
    monkeypatch.setattr(lineage_facets, "build_references_dataset_facet", lambda **kwargs: {"refs": kwargs})

    def _fake_run_pipeline(config: PipelineConfig) -> dict[str, object]:
        output_root = pipeline_module._resolve_project_path(config.output_dir, force_project_drive=True)
        paths = pipeline_module.build_output_paths(output_root)
        for artifact in (
            paths.state_dir / "config_snapshot.json",
            paths.state_dir / "verification.json",
            paths.metrics_dir / "overall_metrics.json",
            paths.strategies_dir / "best_strategy_summary.json",
            paths.reports_dir / "final_report.md",
        ):
            artifact.parent.mkdir(parents=True, exist_ok=True)
            if artifact.suffix == ".json":
                artifact.write_text("{}", encoding="utf-8")
            else:
                artifact.write_text("# report\n", encoding="utf-8")
        return {
            "dataset_build_id": "dataset-build-1",
            "export_panel_version_id": "export-build-1",
        }

    monkeypatch.setattr(pipeline_module, "run_pipeline", _fake_run_pipeline)

    summary = run_pipeline_with_optional_lineage(
        PipelineConfig(input_panel_csv="panel.csv", output_dir="outputs")
    )

    lineage_summary_path = tmp_path / "outputs" / "06_state" / "lineage_summary.json"
    assert lineage_summary_path.exists()
    lineage_summary = json.loads(lineage_summary_path.read_text(encoding="utf-8"))

    assert summary["lineage_run_id"] == lineage_summary["lineage_run_id"]
    assert summary["lineage_event_dir"] == lineage_summary["lineage_event_dir"]
    assert lineage_summary["dataset_build_id"] == "dataset-build-1"
    assert lineage_summary["export_panel_version_id"] == "export-build-1"
    assert [event[0] for event in events] == ["start", "complete"]


def test_build_feature_set_version_is_order_insensitive() -> None:
    assert build_feature_set_version(["beta", "alpha"]) == build_feature_set_version(["alpha", "beta"])


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
