"""Dagster resource mirroring `Pipeline.PipelineConfig` defaults."""

import sys
from pathlib import Path
from typing import List

from dagster import ConfigurableResource
from pydantic import Field

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import Pipeline as Pipeline_mod  # noqa: E402

_TUPLE_KEYS = frozenset(
    {
        "max_concurrent_options",
        "p_min_grid",
        "theta_ev_grid",
        "theta_rel_grid",
        "seed_list_research",
        "seed_list_final",
    }
)


class PipelineConfigResource(ConfigurableResource):
    """Configurable resource with defaults aligned to `Pipeline.PipelineConfig`."""

    input_panel_csv: str = "panel_ohlcv_clean.csv"
    output_dir: str = "pipeline_outputs"
    strategy_report_template: str = "strategy-report.qmd"
    resume: bool = False
    starting_capital: float = 50_000.0
    risk_per_trade: float = 0.03
    max_concurrent_options: List[int] = Field(default_factory=lambda: [8])
    max_positions_per_ticker: int = 2
    slippage_per_fill: float = 0.0001
    overnight_brokerage: float = 0.0003
    max_adv_participation: float = 0.02
    headroom_adv_participation: float = 0.015
    max_clipped_or_skipped_order_fraction: float = 0.05
    max_capacity_drag_fraction_live: float = 0.10
    stop_atr_multiple: float = 1.0
    target_atr_multiple: float = 2.0
    max_horizon_bars: int = 105
    outer_train_months: int = 36
    outer_test_months: int = 6
    inner_folds: int = 5
    embargo_bars: int = 105
    threshold_holdout_months: int = 3
    calibration_holdout_months: int = 2
    p_min_grid: List[float] = Field(
        default_factory=lambda: [
            0.40,
            0.43,
            0.46,
            0.49,
            0.52,
            0.55,
            0.58,
            0.61,
            0.64,
        ]
    )
    theta_ev_grid: List[float] = Field(default_factory=lambda: [0.10, 0.15, 0.20, 0.25])
    theta_rel_grid: List[float] = Field(default_factory=lambda: [1.05, 1.10, 1.15])
    estimated_overnights_for_ranking: int = 3
    threshold_wrc_alpha: float = 0.10
    threshold_wrc_bootstrap_reps: int = 250
    threshold_wrc_block_length: int = 5
    threshold_wrc_min_daily_observations: int = 60
    threshold_wrc_min_nonzero_days: int = 20
    threshold_wrc_min_trades: int = 20
    threshold_wrc_min_avg_active_exposure: float = 0.10
    empirical_prob_map_min_rows: int = 300
    empirical_prob_map_min_bucket_rows: int = 30
    empirical_prob_map_buckets: int = 10
    empirical_prob_map_min_top_bucket_positive_fraction: float = 0.60
    empirical_prob_map_max_fallback_usage_fraction: float = 0.25
    empirical_prob_map_min_adjacent_fold_spearman: float = 0.70
    final_min_oos_daily_observations: int = 126
    rf_n_estimators: int = 300
    rf_max_depth: int = 6
    rf_min_samples_leaf: int = 150
    et_n_estimators: int = 400
    et_max_depth: int = 6
    et_min_samples_leaf: int = 100
    xgb_n_estimators: int = 350
    xgb_learning_rate: float = 0.03
    xgb_max_depth: int = 4
    xgb_min_child_weight: int = 40
    xgb_subsample: float = 0.80
    xgb_colsample_bytree: float = 0.60
    xgb_reg_alpha: float = 1.0
    xgb_reg_lambda: float = 5.0
    lgbm_n_estimators: int = 400
    lgbm_learning_rate: float = 0.03
    lgbm_num_leaves: int = 31
    lgbm_subsample: float = 0.80
    lgbm_colsample_bytree: float = 0.80
    enet_c: float = 0.5
    enet_l1_ratio: float = 0.5
    meta_c: float = 0.1
    calibrator_c: float = 1.0
    include_physics_block: bool = True
    max_missing_feature_fraction: float = 0.35
    bars_per_year: float = 252 * 6.5
    random_seed: int = 42
    n_jobs_tree_models: int = -1
    n_jobs_xgb: int = 8
    deterministic_mode: bool = False
    seed_mode: str = "single"
    seed_list_research: List[int] = Field(default_factory=lambda: [11, 23, 42, 57, 73])
    seed_list_final: List[int] = Field(
        default_factory=lambda: [11, 23, 31, 42, 57, 73, 88, 101, 117, 149]
    )
    use_optuna_tuning: bool = False
    optuna_n_trials: int = 20
    require_baseline_pass_for_tuning: bool = True
    implementation_status: str = "present"
    verification_stage_reached: str = "code_present"
    commission_per_side: float = 0.0
    spread_source: str = "embedded_in_slippage_assumption_v1"
    reject_or_clip_penalty: str = "explicit_capacity_drag"
    idle_cash_treatment: str = "included_in_daily_equity_series"

    def to_pipeline_config(self) -> Pipeline_mod.PipelineConfig:
        data = self.model_dump()
        for key in _TUPLE_KEYS:
            if key in data and data[key] is not None:
                data[key] = tuple(data[key])
        cfg = Pipeline_mod.PipelineConfig(**data)
        cfg.input_panel_csv = str(Pipeline_mod._resolve_project_path(cfg.input_panel_csv))
        cfg.output_dir = str(
            Pipeline_mod._resolve_project_path(cfg.output_dir, force_project_drive=True)
        )
        cfg.strategy_report_template = str(
            Pipeline_mod._resolve_project_path(cfg.strategy_report_template)
        )
        if cfg.deterministic_mode:
            cfg.n_jobs_tree_models = 1
            cfg.n_jobs_xgb = 1
            cfg.seed_mode = "single"
        return cfg
