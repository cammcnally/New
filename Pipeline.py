#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import signal
from statistics import NormalDist
import sys
import tempfile
import time
import uuid
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple, cast
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score  # type: ignore[import-untyped]
from xgboost import XGBClassifier

try:
    import optuna  # type: ignore[import-untyped,import-not-found]
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

try:
    from lightgbm import LGBMClassifier
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

if TYPE_CHECKING:
    from optuna import Trial


class _TrialLike(Protocol):
    """Protocol for Optuna trial so objectives can be typed without requiring optuna stubs."""

    def suggest_int(self, name: str, low: int, high: int, step: int = 1) -> int: ...
    def suggest_float(self, name: str, low: float, high: float, log: bool = False) -> float: ...


class _ClassifierLike(Protocol):
    """Protocol for sklearn-style classifiers (fit, predict_proba) without requiring sklearn stubs."""

    def fit(self, X: Any, y: Any) -> Any: ...
    def predict_proba(self, X: Any) -> Any: ...


warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

SUPPORTED_PYTHON_MIN = (3, 11, 9)
SUPPORTED_PYTHON_MAX_EXCLUSIVE = (3, 12, 0)
OPTUNA_MAX_WALL_CLOCK_SECONDS = 20 * 60


def _require_supported_python_version(version_info: Optional[Tuple[int, int, int]] = None) -> None:
    current = tuple(version_info or tuple(sys.version_info[:3]))
    if current < SUPPORTED_PYTHON_MIN or current >= SUPPORTED_PYTHON_MAX_EXCLUSIVE:
        current_text = ".".join(str(part) for part in current)
        min_text = ".".join(str(part) for part in SUPPORTED_PYTHON_MIN)
        max_text = ".".join(str(part) for part in SUPPORTED_PYTHON_MAX_EXCLUSIVE[:2])
        raise SystemExit(
            "Unsupported Python interpreter for this repository: "
            f"{current_text}. Use >={min_text},<{max_text} from the workspace virtual environment."
        )


_require_supported_python_version()

# ============================================================
# CONFIGURATION
# ============================================================
@dataclass
class PipelineConfig:
    # Input / output
    input_panel_csv: str = "panel_ohlcv_clean.csv"
    output_dir: str = "pipeline_outputs"
    resume: bool = False
    # Capital / execution
    starting_capital: float = 50_000.0
    risk_per_trade: float = 0.03
    max_concurrent_options: Tuple[int, ...] = (8,)
    max_positions_per_ticker: int = 2
    slippage_per_fill: float = 0.0001
    overnight_brokerage: float = 0.0003
    max_adv_participation: float = 0.02
    headroom_adv_participation: float = 0.015
    max_clipped_or_skipped_order_fraction: float = 0.05
    max_capacity_drag_fraction_live: float = 0.10
    # Label geometry
    stop_atr_multiple: float = 1.0
    target_atr_multiple: float = 2.0
    max_horizon_bars: int = 105
    # Walk-forward / CV
    outer_train_months: int = 36  # Initial training span (months). Outer folds use an expanding window, not rolling.
    outer_test_months: int = 6
    inner_folds: int = 5
    embargo_bars: int = 105
    # Threshold holdout (calendar months from end of purged train; used for unbiased threshold selection)
    threshold_holdout_months: int = 3
    # Calibration holdout (calendar months from end of purged fit; used to fit calibrator out-of-sample vs meta-model)
    calibration_holdout_months: int = 2
    # Threshold search
    p_min_grid: Tuple[float, ...] = (0.40, 0.43, 0.46, 0.49, 0.52, 0.55, 0.58, 0.61, 0.64)
    theta_ev_grid: Tuple[float, ...] = (0.10, 0.15, 0.20, 0.25)
    theta_rel_grid: Tuple[float, ...] = (1.05, 1.10, 1.15)
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
    # Base models
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
    # Meta model and calibration
    meta_c: float = 0.1
    calibrator_c: float = 1.0
    # Features
    include_physics_block: bool = True
    max_missing_feature_fraction: float = 0.35
    # Sharpe annualization (must match actual panel bar frequency; e.g. 252*6.5 for hourly US equity bars)
    bars_per_year: float = 252 * 6.5
    # Reproducibility / runtime
    random_seed: int = 42
    n_jobs_tree_models: int = -1
    n_jobs_xgb: int = 8
    deterministic_mode: bool = False
    # Seed robustness
    seed_mode: str = "single"  # "single" | "research" | "final"
    seed_list_research: Tuple[int, ...] = (11, 23, 42, 57, 73)
    seed_list_final: Tuple[int, ...] = (11, 23, 31, 42, 57, 73, 88, 101, 117, 149)
    # Tuning (Optuna, optional). Run baseline first; enable only after baseline_passed().
    use_optuna_tuning: bool = False
    optuna_n_trials: int = 20
    require_baseline_pass_for_tuning: bool = True
    # Verification / artifact semantics
    implementation_status: str = "present"
    verification_stage_reached: str = "code_present"
    # Cost-model schema
    commission_per_side: float = 0.0
    spread_source: str = "embedded_in_slippage_assumption_v1"
    reject_or_clip_penalty: str = "explicit_capacity_drag"
    idle_cash_treatment: str = "included_in_daily_equity_series"


# Minimum rows in threshold holdout for threshold selection to be meaningful
MIN_THRESHOLD_HOLDOUT_ROWS = 50

# Calibration holdout viability (strict; avoids unstable probability calibration)
MIN_CALIBRATION_HOLDOUT_ROWS = 200
MIN_CALIBRATION_HOLDOUT_POS = 25
MIN_CALIBRATION_HOLDOUT_NEG = 25

SCHEMA_VERSION = "2.1.0"
ROBUSTNESS_METHOD_VERSION = "phase1_threshold_wrc_nw_v2"
SEARCH_FAMILY_DEFINITION_VERSION = "threshold_policy_family_v1"
THRESHOLD_SEARCH_CORRECTED = True
FULL_PIPELINE_CORRECTED = False
TRIAL_SCOPE_FORMAL = "threshold_policy_search_only"
FEATURE_VALIDATION_ROW_COLUMNS: Tuple[str, ...] = (
    "fold",
    "feature",
    "family",
    "expected_sign",
    "panel_asset_count",
    "min_assets_per_day",
    "n_ic_days",
    "ic_mean",
    "ic_tstat_hac",
    "positive_fold",
    "regime_positive_count",
    "regime_days_covered",
    "monotonic_top_minus_bottom_mean",
    "monotonic_top_minus_bottom_tstat",
    "adjacent_bucket_ordering_fraction",
    "incremental_lift_after_costs",
    "feature_validation_status",
    "feature_validation_pass",
    "feature_validation_preferred",
)
FEATURE_VALIDATION_DAILY_COLUMNS: Tuple[str, ...] = (
    "timestamp_utc",
    "n_assets",
    "spearman_ic",
    "feature",
    "fold",
    "family",
)
FEATURE_VALIDATION_REPORT_COLUMNS: Tuple[str, ...] = (
    "feature",
    "family",
    "expected_sign",
    "folds_seen",
    "sufficient_folds",
    "positive_fold_fraction",
    "regime_positive_fold_fraction",
    "monotonic_pass_fraction",
    "incremental_lift_positive_fraction",
    "mean_fold_ic",
    "mean_fold_ic_tstat",
    "mean_top_minus_bottom",
    "mean_incremental_lift_after_costs",
    "pooled_ic_mean",
    "pooled_ic_tstat_hac",
    "total_ic_days",
    "english_name",
    "economic_thesis",
    "formula",
    "timestamping_rule",
    "expected_decay_horizon",
    "feature_validation_pass",
    "feature_validation_preferred",
)
MODEL_COMPARISON_ROW_COLUMNS: Tuple[str, ...] = (
    "fold",
    "model_name",
    "max_concurrent",
    "fold_selected",
    "fold_skip_reason",
    "wrc_status",
    "wrc_pvalue",
    "adjusted_oos_sharpe",
    "net_oos_spread_after_costs",
    "profit_factor",
    "max_drawdown",
    "calmar",
    "turnover_notional_to_equity",
    "capacity_drag_fraction_of_gross_alpha",
    "n_trades",
    "n_daily_observations",
    "schema_version",
    "robustness_method_version",
    "search_family_definition_version",
)
MODEL_COMPARISON_REPORT_COLUMNS: Tuple[str, ...] = (
    "model_name",
    "folds_seen",
    "selected_fold_fraction",
    "mean_adjusted_oos_sharpe",
    "mean_net_oos_spread_after_costs",
    "mean_profit_factor",
    "mean_calmar",
    "mean_max_drawdown",
    "mean_turnover_notional_to_equity",
    "mean_capacity_drag_fraction_of_gross_alpha",
    "total_trades",
    "primary_metric_improvement_vs_best_baseline",
    "materially_lower_drawdown_turnover_capacity_drag",
    "model_comparison_pass",
    "schema_version",
    "robustness_method_version",
    "search_family_definition_version",
    "threshold_search_corrected",
    "full_pipeline_corrected",
    "trial_scope_formal",
    "trial_count_formal",
)
POSITION_RANKING_AUDIT_COLUMNS: Tuple[str, ...] = (
    "fold",
    "timestamp_utc",
    "ticker",
    "decision",
    "max_concurrent",
    "p_cal",
    "p_empirical",
    "ev_empirical_r",
    "cost_est_r",
    "signal_dollar_volume",
    "signal_adv_dollar_20",
)


def ensure_columns(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    work = df.copy()
    for column in columns:
        if column not in work.columns:
            work[column] = pd.Series(dtype="object")
    ordered = [column for column in columns if column in work.columns]
    extras = [column for column in work.columns if column not in ordered]
    return work[ordered + extras]
SCORECARD_LABEL = "scorecard_default_thresholds_v1"
SCORECARD_ARCHETYPE = "concentrated_multi_day_strategy_max8"
IMPLEMENTATION_STATUS_VALUES: Tuple[str, ...] = (
    "planned",
    "present",
    "unit_tested",
    "smoke_validated",
    "reproducible_verified",
)

NORMAL_DIST = NormalDist()
_EULER_GAMMA = 0.5772156649015329


CORE_FEATURES: List[str] = [
    # Returns and momentum
    "ret_1", "ret_2", "ret_3", "ret_5", "ret_8", "ret_10", "ret_13", "ret_20", "ret_21", "ret_34", "ret_55",
    "logret_1", "roc_5", "roc_10", "roc_20",
    "ret_z_13", "ret_z_34", "cumret_13", "cumret_34", "cumret_55", "up_bar_ratio_13", "up_bar_ratio_34",
    "momentum_5_over_21", "momentum_13_over_34",
    # Trend / moving averages
    "ema_gap_5_13", "ema_gap_10_20", "ema_gap_13_34", "ema_gap_20_50", "ema_gap_34_55", "ema_gap_55_89",
    "sma_gap_13_34", "sma_gap_34_55",
    "price_vs_ema_13", "price_vs_ema20", "price_vs_ema_34", "price_vs_ema50", "price_vs_ema_55",
    "price_vs_sma_21", "price_vs_sma_55", "ema_slope_13", "ema_slope_34", "ema_slope_55",
    "trend_persistence_13", "trend_persistence_34",
    # Oscillators
    "rsi_7", "rsi_14", "rsi_21", "stoch_k_14_3", "stoch_d_14_3", "stoch_k_21_3", "stoch_d_21_3",
    "williams_r_14", "williams_r_21", "cci_20", "cci_34",
    # MACD / PPO
    "macd_12_26_9", "macd_signal_12_26_9", "macd_hist_12_26_9",
    "macd_13_34_8", "macd_signal_13_34_8", "macd_hist_13_34_8", "ppo_12_26",
    # Volatility / range / channels
    "atr_14", "atr_21", "atr_34", "atr_pct_14", "atr_pct_21", "atr_pct_34", "tr_pct_1",
    "bb_pos_20_2", "bb_width_20_2", "bb_pos_34_2", "bb_width_34_2", "keltner_pos_20_2", "keltner_width_20_2",
    "donchian_pos_20", "donchian_pos_55", "breakout_up_20", "breakout_up_55", "breakout_down_20", "breakout_down_55",
    "squeeze_on_20",
    "range_pct_1", "range_pct_5", "range_pct_13",
    "realized_vol_10", "realized_vol_20", "realized_vol_13", "realized_vol_34", "realized_vol_89",
    "vol_of_vol_13", "vol_of_vol_20", "vol_of_vol_34", "parkinson_vol_13", "parkinson_vol_34", "garman_klass_vol_13",
    # Directional movement
    "adx_14", "adx_21", "plus_di_14", "minus_di_14", "plus_di_21", "minus_di_21", "adx_slope_5",
    # Volume / flow
    "vol_z_20", "vol_z_60", "rel_volume_20", "rel_volume_60", "volume_ema_gap_10_20",
    "obv", "obv_slope_5", "obv_slope_13", "cmf_20", "mfi_14", "force_index_13", "vpt_slope_13",
    # VWAP / support / resistance / bar anatomy
    "session_vwap_dist", "rolling_vwap_dist_13", "rolling_vwap_dist_34", "pivot_dist_prev_day",
    "dist_to_roll_high_20", "dist_to_roll_high_55", "dist_to_roll_low_20", "dist_to_roll_low_55",
    "range_position_20", "range_position_55",
    "body_pct_1", "upper_wick_pct_1", "lower_wick_pct_1", "close_location_value_1", "gap_open_pct_1",
]
PHYSICS_FEATURES: List[str] = [
    "hurst_proxy_34", "hurst_proxy_50", "hurst_proxy_55", "hurst_proxy_89",
    "variance_ratio_5_34", "variance_ratio_5_55", "variance_ratio_13_89",
    "entropy_sign_20", "entropy_sign_34", "entropy_sign_55",
    "entropy_return_hist_20", "entropy_return_hist_34",
    "autocorr_1_20", "autocorr_5_20", "autocorr_1_34", "autocorr_5_34",
    "autocorr_absret_1_20", "autocorr_absret_1_34",
    "fracret_0_35", "fracret_0_50",
    "fractal_dimension_proxy_20", "fractal_dimension_proxy_34", "fractal_dimension_proxy_55",
    "pfe_13", "pfe_34", "roughness_index_20", "roughness_index_34",
    "rolling_skew_34", "rolling_kurt_34",
]

# Volatility-clustering and regime context features implemented in this file.
VOLATILITY_CLUSTERING_FEATURES: List[str] = [
    "vol_pct_rank_34",
    "vol_pct_rank_89",
    "vol_cluster_high_34",
    "vol_cluster_low_34",
    "vol_persistence_high_13",
    "vol_persistence_high_34",
    "vol_persistence_low_13",
    "vol_persistence_low_34",
    "consecutive_high_vol_bars",
    "consecutive_low_vol_bars",
    "regime_duration_high_vol",
    "regime_duration_low_vol",
    "vol_regime_change_5",
    "vol_regime_change_13",
    "vol_spike_flag",
    "vol_cooling_flag",
    "vol_x_momentum_13",
    "vol_x_trend_strength",
    "vol_x_breakout_state",
    "vol_x_rel_volume",
]

# Cross-sectional z-score features implemented in this file.
XS_FEATURES: List[str] = [
    "xs_ret_5_z",
    "xs_ret_13_z",
    "xs_ret_20_z",
    "xs_ret_34_z",
    "xs_rsi_14_z",
    "xs_atr_pct_14_z",
    "xs_rel_volume_20_z",
]

BASE_MODEL_ORDER: Tuple[str, ...] = ("RF", "ET", "XGB", "LGBM", "ENET")

# Canonical registry schema fields. The registry builder below uses these keys.
REGISTRY_FIELDS: Tuple[str, ...] = (
    "feature_name",
    "english_name",
    "family",
    "subfamily",
    "regular_or_physics",
    "lookback",
    "formula",
    "timestamping_rule",
    "economic_thesis",
    "expected_sign",
    "expected_decay_horizon",
    "parameters",
    "formula_group",
    "default_enabled",
    "implementation_status",
    "availability_status",
    "depends_on",
    "candidate_group_id",
    "orthogonality_cluster_id",
    "family_cap_weight",
    "interpretability_tag",
    "requires_external_reference",
    "notes",
    "disabled_reason",
)

# ============================================================
# UTILITIES
# ============================================================
@dataclass(frozen=True)
class OutputPaths:
    root: Path
    logs_dir: Path
    data_dir: Path
    metrics_dir: Path
    features_dir: Path
    strategies_dir: Path
    reports_dir: Path
    state_dir: Path


def build_output_paths(output_root: Path) -> OutputPaths:
    paths = OutputPaths(
        root=output_root,
        logs_dir=output_root / "00_logs",
        data_dir=output_root / "01_data",
        metrics_dir=output_root / "02_metrics",
        features_dir=output_root / "03_features",
        strategies_dir=output_root / "04_strategies",
        reports_dir=output_root / "05_reports",
        state_dir=output_root / "06_state",
    )
    for p in (
        paths.logs_dir,
        paths.data_dir,
        paths.metrics_dir,
        paths.features_dir,
        paths.strategies_dir,
        paths.reports_dir,
        paths.state_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)
    return paths


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: object) -> None:
    atomic_write_text(path, json.dumps(sanitize_for_json(payload), indent=2))


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            df.to_csv(f, index=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def invalidate_stale_reports(paths: OutputPaths) -> None:
    """Delete known summary/report artifacts if required upstream artifacts are missing.
    Avoids leaving behind stale reports from prior successful runs."""
    required_paths = [
        paths.metrics_dir / "fold_metrics.csv",
    ]
    missing = [p for p in required_paths if not p.exists()]
    if not missing:
        return
    stale_targets = [
        paths.metrics_dir / "overall_metrics.json",
        paths.metrics_dir / "threshold_candidate_diagnostics.csv",
        paths.metrics_dir / "policy_daily_returns.csv",
        paths.reports_dir / "final_report.md",
        paths.reports_dir / "equity_curve_best_concurrency.png",
        paths.metrics_dir / "trade_blotter.csv",
        paths.metrics_dir / "equity_curves.csv",
        paths.features_dir / "feature_stability_summary.csv",
        paths.features_dir / "ranked_feature_table.csv",
        paths.features_dir / "family_importance_table.csv",
        paths.strategies_dir / "strategy_library.csv",
        paths.strategies_dir / "best_strategy_summary.json",
    ]
    for target in stale_targets:
        if target.exists():
            target.unlink(missing_ok=True)


def verify_panel_timestamp_regularity(
    panel: pd.DataFrame,
    *,
    ticker_col: str = "ticker",
    time_col: str = "timestamp_utc",
) -> Dict[str, Any]:
    """Checks how well each ticker aligns to the global timestamp set.
    Useful when purged/embargo splits are defined in units of global timestamps (MR1).
    Distinguishes late-start tickers (IPO, etc.) from scattered gaps: only low span_coverage
    within a ticker's own time span indicates embargo-weakening gaps."""
    x = panel[[ticker_col, time_col]].copy()
    x[time_col] = pd.to_datetime(x[time_col], utc=True)
    global_ts = pd.Index(sorted(x[time_col].dropna().unique()))
    n_global = int(len(global_ts))
    per_ticker = (
        x.groupby(ticker_col)[time_col]
        .nunique()
        .rename("n_timestamps")
        .reset_index()
    )
    per_ticker["global_timestamp_coverage"] = per_ticker["n_timestamps"] / max(n_global, 1)
    per_ticker["missing_global_timestamps"] = n_global - per_ticker["n_timestamps"]
    # Span coverage: within each ticker's own [first_ts, last_ts], what fraction of global
    # timestamps does the ticker have? Late-start tickers (e.g. IPO) have low global_coverage
    # but high span_coverage; scattered gaps yield low span_coverage.
    first_last = x.groupby(ticker_col)[time_col].agg(["min", "max"])
    first_last.columns = ["first_ts", "last_ts"]
    per_ticker = per_ticker.merge(first_last, on=ticker_col, how="left")
    n_global_in_span_list: List[int] = []
    for _, row in per_ticker.iterrows():
        in_span = (global_ts >= row["first_ts"]) & (global_ts <= row["last_ts"])
        n_global_in_span_list.append(int(in_span.sum()))
    per_ticker["n_global_in_span"] = n_global_in_span_list
    per_ticker["span_coverage"] = per_ticker["n_timestamps"] / per_ticker["n_global_in_span"].replace(0, 1)
    duplicates = int(x.groupby([ticker_col, time_col]).size().gt(1).sum())
    diffs = (
        x.sort_values([ticker_col, time_col])
        .groupby(ticker_col)[time_col]
        .diff()
        .dropna()
    )
    diff_seconds = diffs.dt.total_seconds()
    coverage_stats = {
        "min_coverage": float(per_ticker["global_timestamp_coverage"].min()) if not per_ticker.empty else math.nan,
        "median_coverage": float(per_ticker["global_timestamp_coverage"].median()) if not per_ticker.empty else math.nan,
        "max_coverage": float(per_ticker["global_timestamp_coverage"].max()) if not per_ticker.empty else math.nan,
        "tickers_below_95pct": int((per_ticker["global_timestamp_coverage"] < 0.95).sum()) if not per_ticker.empty else 0,
        "tickers_below_90pct": int((per_ticker["global_timestamp_coverage"] < 0.90).sum()) if not per_ticker.empty else 0,
        "tickers_below_95pct_span": int((per_ticker["span_coverage"] < 0.95).sum()) if not per_ticker.empty else 0,
        "tickers_below_90pct_span": int((per_ticker["span_coverage"] < 0.90).sum()) if not per_ticker.empty else 0,
    }
    cadence_stats = {
        "median_delta_seconds": float(diff_seconds.median()) if not diff_seconds.empty else math.nan,
        "p95_delta_seconds": float(diff_seconds.quantile(0.95)) if not diff_seconds.empty else math.nan,
        "max_delta_seconds": float(diff_seconds.max()) if not diff_seconds.empty else math.nan,
    }
    return {
        "n_global_timestamps": n_global,
        "n_tickers": int(per_ticker[ticker_col].nunique()) if not per_ticker.empty else 0,
        "duplicate_ticker_timestamp_rows": duplicates,
        "coverage_summary": coverage_stats,
        "cadence_summary": cadence_stats,
        "per_ticker": per_ticker.sort_values(["span_coverage", ticker_col], ascending=[True, True]),
    }


def write_panel_regularity_outputs(output_dir: Path, diagnostics: Dict[str, Any]) -> None:
    """Write panel timestamp regularity diagnostics to 00_logs/."""
    paths = build_output_paths(output_dir)
    payload = {k: v for k, v in diagnostics.items() if k != "per_ticker"}
    atomic_write_json(paths.logs_dir / "panel_timestamp_regularity_summary.json", payload)
    per_ticker = diagnostics.get("per_ticker")
    if isinstance(per_ticker, pd.DataFrame):
        atomic_write_csv(per_ticker, paths.logs_dir / "panel_timestamp_regularity_by_ticker.csv")


def spearman_ic_by_timestamp(
    frame: pd.DataFrame,
    *,
    score_col: str,
    outcome_col: str,
    timestamp_col: str = "timestamp_utc",
    min_n: int = 5,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Blueprint-style IC: cross-sectional Spearman per timestamp, then aggregate (MR3)."""
    required = [score_col, outcome_col, timestamp_col]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        return pd.DataFrame(), {"n_timestamps": 0, "mean_ic": math.nan, "std_ic": math.nan, "ic_ir": math.nan, "positive_ic_hit_rate": math.nan}
    x = frame[required].copy()
    x = x.dropna(subset=[score_col, outcome_col, timestamp_col])
    x[timestamp_col] = pd.to_datetime(x[timestamp_col], utc=True)
    rows: List[Dict[str, Any]] = []
    for ts, g in x.groupby(timestamp_col, sort=True):
        if len(g) < min_n:
            continue
        ic = g[score_col].corr(g[outcome_col], method="spearman")
        rows.append({timestamp_col: ts, "n": int(len(g)), "spearman_ic": float(ic) if pd.notna(ic) else math.nan})
    ic_ts = pd.DataFrame(rows)
    if ic_ts.empty:
        return ic_ts, {"n_timestamps": 0, "mean_ic": math.nan, "std_ic": math.nan, "ic_ir": math.nan, "positive_ic_hit_rate": math.nan}
    mean_ic = float(ic_ts["spearman_ic"].mean())
    std_ic = float(ic_ts["spearman_ic"].std(ddof=1)) if len(ic_ts) > 1 else math.nan
    return ic_ts, {
        "n_timestamps": int(len(ic_ts)),
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "ic_ir": float(mean_ic / std_ic) if std_ic and pd.notna(std_ic) and std_ic != 0 else math.nan,
        "positive_ic_hit_rate": float((ic_ts["spearman_ic"] > 0).mean()),
    }


def winsorize_series(series: pd.Series, lower_q: float = 0.005, upper_q: float = 0.995) -> pd.Series:
    values = pd.Series(series, dtype=float).replace([np.inf, -np.inf], np.nan)
    clean = values.dropna()
    if len(clean) < 3:
        return values
    lower = float(clean.quantile(lower_q))
    upper = float(clean.quantile(upper_q))
    return values.clip(lower=lower, upper=upper)


def hac_mean_tstat(values: Sequence[float]) -> float:
    series = pd.Series(list(values), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2:
        return math.nan
    mean_value = float(series.mean())
    centered = series - mean_value
    lag = min(5, int(math.floor(len(series) ** 0.25)))
    vals = centered.to_numpy()
    gamma0 = float(np.mean(vals * vals))
    long_run_var = gamma0
    for idx in range(1, lag + 1):
        cov = float(np.mean(vals[idx:] * vals[:-idx]))
        weight = 1.0 - idx / (lag + 1.0)
        long_run_var += 2.0 * weight * cov
    if long_run_var <= 0:
        return math.nan
    se = math.sqrt(long_run_var / len(series))
    if se <= 0:
        return math.nan
    return float(mean_value / se)


def _pct_rank_by_timestamp(values: pd.Series, timestamps: pd.Series) -> pd.Series:
    tmp = pd.DataFrame({"value": values.astype(float), "timestamp_utc": pd.to_datetime(timestamps, utc=True)})
    ranked = tmp.groupby("timestamp_utc")["value"].rank(method="average", pct=True)
    return ranked.astype(float)


def _cross_section_bucket_metrics(
    frame: pd.DataFrame,
    *,
    score_col: str,
    outcome_col: str,
    timestamp_col: str,
    min_assets: int,
    buckets: int,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    work = frame[[score_col, outcome_col, timestamp_col]].copy()
    work = work.replace([np.inf, -np.inf], np.nan).dropna()
    if work.empty:
        return pd.DataFrame()
    work[timestamp_col] = pd.to_datetime(work[timestamp_col], utc=True)
    for ts, group in work.groupby(timestamp_col, sort=True):
        if len(group) < min_assets:
            continue
        pct_rank = group[score_col].rank(method="average", pct=True)
        bucket = np.ceil(pct_rank * buckets).clip(1, buckets).astype(int)
        grouped = group.assign(bucket=bucket).groupby("bucket")[outcome_col].mean().reindex(range(1, buckets + 1))
        if grouped.notna().sum() < max(3, buckets // 2):
            continue
        top = grouped.iloc[-1]
        bottom = grouped.iloc[0]
        top_minus_bottom = float(top - bottom) if pd.notna(top) and pd.notna(bottom) else math.nan
        valid = grouped.dropna().to_numpy(dtype=float)
        if len(valid) >= 2:
            adjacent_fraction = float((np.diff(valid) >= -1e-12).mean())
        else:
            adjacent_fraction = math.nan
        top_bucket_incremental_lift = float(top - group[outcome_col].mean()) if pd.notna(top) else math.nan
        rows.append(
            {
                timestamp_col: ts,
                "bucket_count": int(grouped.notna().sum()),
                "top_minus_bottom": top_minus_bottom,
                "adjacent_ordering_fraction": adjacent_fraction,
                "top_bucket_incremental_lift": top_bucket_incremental_lift,
            }
        )
    return pd.DataFrame(rows)


def _expected_sign_multiplier(expected_sign: object) -> int:
    value = str(expected_sign or "mixed").strip().lower()
    if value.startswith("neg"):
        return -1
    return 1


def _empty_feature_validation_row(
    *,
    fold_name: str,
    feature_name: str,
    meta: Mapping[str, Any],
    expected_sign: str,
    panel_asset_count: int,
    min_assets_per_day: int,
) -> Dict[str, Any]:
    return {
        "fold": fold_name,
        "feature": feature_name,
        "family": meta.get("family", "unknown"),
        "expected_sign": expected_sign,
        "panel_asset_count": panel_asset_count,
        "min_assets_per_day": min_assets_per_day,
        "n_ic_days": 0,
        "ic_mean": math.nan,
        "ic_tstat_hac": math.nan,
        "positive_fold": 0,
        "regime_positive_count": 0,
        "regime_days_covered": 0,
        "monotonic_top_minus_bottom_mean": math.nan,
        "monotonic_top_minus_bottom_tstat": math.nan,
        "adjacent_bucket_ordering_fraction": math.nan,
        "incremental_lift_after_costs": math.nan,
        "feature_validation_status": "insufficient_data",
        "feature_validation_pass": 0,
        "feature_validation_preferred": 0,
    }


def feature_validation_for_fold(
    scored_df: pd.DataFrame,
    feature_registry_df: pd.DataFrame,
    fold_name: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    registry_lookup = (
        feature_registry_df.set_index("feature_name").to_dict("index")
        if len(feature_registry_df)
        else {}
    )
    panel_asset_count = int(scored_df["ticker"].nunique()) if "ticker" in scored_df.columns else 0
    min_assets_per_day = max(2, min(20, int(math.ceil(max(panel_asset_count, 1) * 0.70))))
    timestamp_col = "timestamp_utc"
    rows: List[Dict[str, Any]] = []
    daily_rows: List[Dict[str, Any]] = []
    if len(scored_df) == 0:
        return rows, daily_rows
    if "forward_label_return_net" not in scored_df.columns or timestamp_col not in scored_df.columns:
        for feature_name in feature_registry_df["feature_name"].tolist():
            meta = registry_lookup.get(feature_name, {})
            expected_sign = str(meta.get("expected_sign", "mixed"))
            rows.append(
                _empty_feature_validation_row(
                    fold_name=fold_name,
                    feature_name=feature_name,
                    meta=meta,
                    expected_sign=expected_sign,
                    panel_asset_count=panel_asset_count,
                    min_assets_per_day=min_assets_per_day,
                )
            )
        return rows, daily_rows
    session_dates = pd.to_datetime(scored_df[timestamp_col], utc=True).dt.tz_convert("America/New_York").dt.date
    for feature_name in feature_registry_df["feature_name"].tolist():
        if feature_name not in scored_df.columns:
            continue
        meta = registry_lookup.get(feature_name, {})
        expected_sign = str(meta.get("expected_sign", "mixed"))
        direction = _expected_sign_multiplier(expected_sign)
        work = scored_df[[feature_name, "forward_label_return_net", timestamp_col]].copy()
        work[timestamp_col] = pd.to_datetime(work[timestamp_col], utc=True)
        work["feature_value"] = winsorize_series(work[feature_name].astype(float)) * direction
        work["forward_label_return_net"] = pd.Series(work["forward_label_return_net"], dtype=float)
        work["regime_label"] = infer_regime_label(scored_df).reindex(work.index)
        work["session_date_ny"] = session_dates.astype(str).values
        work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=["feature_value", "forward_label_return_net", timestamp_col])
        if work.empty:
            rows.append(
                _empty_feature_validation_row(
                    fold_name=fold_name,
                    feature_name=feature_name,
                    meta=meta,
                    expected_sign=expected_sign,
                    panel_asset_count=panel_asset_count,
                    min_assets_per_day=min_assets_per_day,
                )
            )
            continue
        ic_ts, ic_summary = spearman_ic_by_timestamp(
            work.rename(columns={"feature_value": "score"}),
            score_col="score",
            outcome_col="forward_label_return_net",
            timestamp_col=timestamp_col,
            min_n=min_assets_per_day,
        )
        ic_tstat = hac_mean_tstat(ic_ts["spearman_ic"].tolist()) if len(ic_ts) else math.nan
        bucket_df = _cross_section_bucket_metrics(
            work,
            score_col="feature_value",
            outcome_col="forward_label_return_net",
            timestamp_col=timestamp_col,
            min_assets=min_assets_per_day,
            buckets=10,
        )
        top_bottom_mean = float(bucket_df["top_minus_bottom"].mean()) if len(bucket_df) else math.nan
        top_bottom_tstat = hac_mean_tstat(bucket_df["top_minus_bottom"].tolist()) if len(bucket_df) else math.nan
        adjacent_fraction = float(bucket_df["adjacent_ordering_fraction"].mean()) if len(bucket_df) else math.nan
        incremental_lift = float(bucket_df["top_bucket_incremental_lift"].mean()) if len(bucket_df) else math.nan
        regime_positive_count = 0
        regime_days_covered = 0
        for regime_name, regime_group in work.groupby("regime_label", sort=True):
            if str(regime_name) == "unknown":
                continue
            n_regime_days = int(pd.Series(regime_group["session_date_ny"]).nunique())
            if n_regime_days < 40:
                continue
            regime_days_covered += n_regime_days
            _, regime_ic_summary = spearman_ic_by_timestamp(
                regime_group.rename(columns={"feature_value": "score"}),
                score_col="score",
                outcome_col="forward_label_return_net",
                timestamp_col=timestamp_col,
                min_n=min_assets_per_day,
            )
            if float(regime_ic_summary.get("mean_ic", math.nan)) > 0:
                regime_positive_count += 1
        sufficient = int(ic_summary.get("n_timestamps", 0)) >= 60
        monotonic_pass = (
            np.isfinite(top_bottom_mean)
            and top_bottom_mean > 0
            and np.isfinite(top_bottom_tstat)
            and top_bottom_tstat >= 2.0
            and np.isfinite(adjacent_fraction)
            and adjacent_fraction >= 0.70
        )
        validation_pass = bool(
            sufficient
            and np.isfinite(ic_tstat)
            and ic_tstat >= 2.0
            and float(ic_summary.get("mean_ic", math.nan)) > 0
            and regime_positive_count >= 2
            and monotonic_pass
            and np.isfinite(incremental_lift)
            and incremental_lift > 0
        )
        preferred_pass = bool(validation_pass and ic_tstat >= 3.0)
        rows.append(
            {
                "fold": fold_name,
                "feature": feature_name,
                "family": meta.get("family", "unknown"),
                "expected_sign": expected_sign,
                "panel_asset_count": panel_asset_count,
                "min_assets_per_day": min_assets_per_day,
                "n_ic_days": int(ic_summary.get("n_timestamps", 0)),
                "ic_mean": float(ic_summary.get("mean_ic", math.nan)),
                "ic_tstat_hac": float(ic_tstat) if np.isfinite(ic_tstat) else math.nan,
                "positive_fold": int(float(ic_summary.get("mean_ic", math.nan)) > 0),
                "regime_positive_count": int(regime_positive_count),
                "regime_days_covered": int(regime_days_covered),
                "monotonic_top_minus_bottom_mean": top_bottom_mean,
                "monotonic_top_minus_bottom_tstat": float(top_bottom_tstat) if np.isfinite(top_bottom_tstat) else math.nan,
                "adjacent_bucket_ordering_fraction": adjacent_fraction,
                "incremental_lift_after_costs": incremental_lift,
                "feature_validation_status": "ok" if sufficient else "insufficient_data",
                "feature_validation_pass": int(validation_pass),
                "feature_validation_preferred": int(preferred_pass),
            }
        )
        if len(ic_ts):
            ic_daily = ic_ts.copy()
            ic_daily["fold"] = fold_name
            ic_daily["feature"] = feature_name
            ic_daily["family"] = meta.get("family", "unknown")
            daily_rows.extend(ic_daily.to_dict("records"))
    return rows, daily_rows


def build_feature_validation_report(
    feature_validation_rows: pd.DataFrame,
    feature_validation_daily: pd.DataFrame,
    feature_registry_df: pd.DataFrame,
) -> pd.DataFrame:
    if feature_validation_rows.empty:
        return pd.DataFrame(columns=FEATURE_VALIDATION_REPORT_COLUMNS)
    rows = feature_validation_rows.copy()
    for column in (
        "family",
        "expected_sign",
        "feature_validation_status",
        "positive_fold",
        "regime_positive_count",
        "monotonic_top_minus_bottom_tstat",
        "monotonic_top_minus_bottom_mean",
        "incremental_lift_after_costs",
        "ic_mean",
        "ic_tstat_hac",
    ):
        if column not in rows.columns:
            rows[column] = np.nan
    report = (
        rows.groupby("feature", as_index=False)
        .agg(
            family=("family", "first"),
            expected_sign=("expected_sign", "first"),
            folds_seen=("fold", "nunique"),
            sufficient_folds=("feature_validation_status", lambda s: int((pd.Series(s).astype(str) == "ok").sum())),
            positive_fold_fraction=("positive_fold", "mean"),
            regime_positive_fold_fraction=("regime_positive_count", lambda s: float((pd.Series(s).astype(float) >= 2).mean())),
            monotonic_pass_fraction=("monotonic_top_minus_bottom_tstat", lambda s: float((pd.Series(s).astype(float) >= 2.0).mean())),
            incremental_lift_positive_fraction=("incremental_lift_after_costs", lambda s: float((pd.Series(s).astype(float) > 0).mean())),
            mean_fold_ic=("ic_mean", "mean"),
            mean_fold_ic_tstat=("ic_tstat_hac", "mean"),
            mean_top_minus_bottom=("monotonic_top_minus_bottom_mean", "mean"),
            mean_incremental_lift_after_costs=("incremental_lift_after_costs", "mean"),
        )
    )
    if not feature_validation_daily.empty:
        pooled_rows: List[Dict[str, Any]] = []
        for feature_name, group in feature_validation_daily.groupby("feature", sort=True):
            pooled_rows.append(
                {
                    "feature": feature_name,
                    "pooled_ic_mean": float(group["spearman_ic"].mean()),
                    "pooled_ic_tstat_hac": float(hac_mean_tstat(group["spearman_ic"].tolist())),
                    "total_ic_days": int(len(group)),
                }
            )
        report = report.merge(pd.DataFrame(pooled_rows), on="feature", how="left")
    else:
        report["pooled_ic_mean"] = math.nan
        report["pooled_ic_tstat_hac"] = math.nan
        report["total_ic_days"] = 0
    report = report.merge(
        feature_registry_df[
            [
                "feature_name",
                "english_name",
                "economic_thesis",
                "formula",
                "timestamping_rule",
                "expected_decay_horizon",
            ]
        ],
        left_on="feature",
        right_on="feature_name",
        how="left",
    ).drop(columns=["feature_name"])
    report["feature_validation_pass"] = (
        (report["pooled_ic_tstat_hac"] >= 2.0)
        & (report["positive_fold_fraction"] >= 0.60)
        & (report["regime_positive_fold_fraction"] >= 0.60)
        & (report["monotonic_pass_fraction"] >= 0.60)
        & (report["incremental_lift_positive_fraction"] >= 0.60)
    ).astype(int)
    report["feature_validation_preferred"] = (
        (report["pooled_ic_tstat_hac"] >= 3.0)
        & (report["positive_fold_fraction"] >= 0.70)
        & (report["feature_validation_pass"] == 1)
    ).astype(int)
    report["schema_version"] = SCHEMA_VERSION
    report["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
    report["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
    return report.sort_values(
        ["feature_validation_pass", "feature_validation_preferred", "pooled_ic_tstat_hac", "mean_fold_ic"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def setup_logging(paths: OutputPaths, resume: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(paths.logs_dir / "pipeline.log", mode=("a" if resume else "w")),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logging.info("=== %s RUN START ===", "RESUME" if resume else "FRESH")


def clip_prob(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    return np.clip(p, 1e-6, 1 - 1e-6)


def logit(p: np.ndarray) -> np.ndarray:
    p = clip_prob(p)
    return np.log(p / (1.0 - p))


def calibration_holdout_is_viable(df: pd.DataFrame) -> Tuple[bool, str, Dict[str, Any]]:
    """Return (ok, reason, stats) for calibration holdout viability.
    reason is formatted to be appended after: 'Skipping {fold_name}: '.
    """
    rows = int(len(df))
    pos = int(df["long_win"].astype(int).sum()) if rows else 0
    neg = int(rows - pos)
    pos_rate = float(pos / rows) if rows else 0.0
    stats: Dict[str, Any] = {
        "calibration_holdout_rows": rows,
        "calibration_holdout_pos_count": pos,
        "calibration_holdout_neg_count": neg,
        "calibration_holdout_pos_rate": pos_rate,
    }
    ok = (
        rows >= MIN_CALIBRATION_HOLDOUT_ROWS
        and pos >= MIN_CALIBRATION_HOLDOUT_POS
        and neg >= MIN_CALIBRATION_HOLDOUT_NEG
    )
    if ok:
        return True, "", stats
    reason = (
        "calibration holdout failed viability check | "
        f"rows={rows} | pos={pos} | neg={neg} | "
        f"required rows>={MIN_CALIBRATION_HOLDOUT_ROWS}, "
        f"pos>={MIN_CALIBRATION_HOLDOUT_POS}, "
        f"neg>={MIN_CALIBRATION_HOLDOUT_NEG}"
    )
    return False, reason, stats


def annualized_cagr(
    start_value: float, end_value: float, start_ts: pd.Timestamp, end_ts: pd.Timestamp
) -> float:
    if start_value <= 0 or end_value <= 0:
        return -1.0
    years = max((end_ts - start_ts).days / 365.25, 1 / 365.25)
    return (end_value / start_value) ** (1 / years) - 1


def estimate_cost_r_from_frame(df: pd.DataFrame, config: PipelineConfig) -> pd.Series:
    entry = df["entry_open_next"].astype(float)
    atr = df["atr_14"].astype(float)
    risk_per_share = config.stop_atr_multiple * atr
    per_share_cost = entry * (
        2 * config.slippage_per_fill
        + config.estimated_overnights_for_ranking * config.overnight_brokerage
    )
    out = per_share_cost / risk_per_share.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def session_dates_from_frame(df: pd.DataFrame) -> List[str]:
    if len(df) == 0 or "timestamp_utc" not in df.columns:
        return []
    ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    return sorted(ts.dt.tz_convert("America/New_York").dt.date.astype(str).drop_duplicates().tolist())


def _empty_daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "session_date_ny",
            "equity",
            "daily_return",
            "active_positions_mean",
            "active_positions_p95",
            "active_positions_max",
            "active_exposure_mean",
        ]
    )


def build_daily_equity_frame(
    equity_df: pd.DataFrame,
    session_dates: Sequence[str],
    starting_capital: float,
    max_concurrent: int,
) -> pd.DataFrame:
    if len(session_dates) == 0:
        return _empty_daily_frame()
    if len(equity_df) == 0:
        out = pd.DataFrame({"session_date_ny": list(session_dates)})
        out["equity"] = float(starting_capital)
        out["daily_return"] = 0.0
        out["active_positions_mean"] = 0.0
        out["active_positions_p95"] = 0.0
        out["active_positions_max"] = 0.0
        out["active_exposure_mean"] = 0.0
        return out

    tmp = equity_df.copy()
    tmp["timestamp_utc"] = pd.to_datetime(tmp["timestamp_utc"], utc=True)
    tmp["session_date_ny"] = tmp["timestamp_utc"].dt.tz_convert("America/New_York").dt.date.astype(str)
    if "active_positions" not in tmp.columns:
        tmp["active_positions"] = 0.0

    def _p95(series: pd.Series) -> float:
        vals = pd.Series(series).astype(float).dropna()
        if vals.empty:
            return 0.0
        return float(np.quantile(vals, 0.95))

    daily = (
        tmp.groupby("session_date_ny", as_index=False)
        .agg(
            equity=("equity", "last"),
            active_positions_mean=("active_positions", "mean"),
            active_positions_p95=("active_positions", _p95),
            active_positions_max=("active_positions", "max"),
        )
    )
    calendar = pd.DataFrame({"session_date_ny": list(session_dates)})
    daily = calendar.merge(daily, on="session_date_ny", how="left")
    daily["equity"] = daily["equity"].ffill().fillna(float(starting_capital))
    for col in ("active_positions_mean", "active_positions_p95", "active_positions_max"):
        daily[col] = daily[col].fillna(0.0).astype(float)
    base_equity = daily["equity"].shift(1).fillna(float(starting_capital))
    daily["daily_return"] = np.where(
        base_equity.abs() > 0,
        daily["equity"].astype(float) / base_equity.astype(float) - 1.0,
        0.0,
    )
    denom = float(max(max_concurrent, 1))
    daily["active_exposure_mean"] = daily["active_positions_mean"] / denom
    return daily


def compute_daily_return_diagnostics(
    daily_returns: Sequence[float],
    *,
    annualization_factor: float = 252.0,
) -> Dict[str, float]:
    series = pd.Series(list(daily_returns), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2:
        return {
            "n_daily_observations": int(len(series)),
            "n_nonzero_return_days": int((series != 0).sum()),
            "sharpe_daily_raw": 0.0,
            "adjusted_sharpe_daily": 0.0,
            "adjusted_sharpe_lag": 0,
        }
    mean_ret = float(series.mean())
    std_ret = float(series.std(ddof=1))
    raw_sharpe = float(mean_ret / std_ret * math.sqrt(annualization_factor)) if std_ret > 0 else 0.0
    lag = min(5, int(math.floor(len(series) ** 0.25)))
    centered = series - mean_ret
    gamma0 = float(np.mean(centered.to_numpy() * centered.to_numpy()))
    long_run_var = gamma0
    vals = centered.to_numpy()
    for idx in range(1, lag + 1):
        cov = float(np.mean(vals[idx:] * vals[:-idx]))
        weight = 1.0 - idx / (lag + 1.0)
        long_run_var += 2.0 * weight * cov
    if long_run_var <= 0:
        adjusted_sharpe = 0.0
    else:
        adjusted_sharpe = float(mean_ret / math.sqrt(long_run_var) * math.sqrt(annualization_factor))
    return {
        "n_daily_observations": int(len(series)),
        "n_nonzero_return_days": int((series.abs() > 1e-12).sum()),
        "sharpe_daily_raw": raw_sharpe,
        "adjusted_sharpe_daily": adjusted_sharpe,
        "adjusted_sharpe_lag": int(lag),
    }


def compute_sortino_ratio(
    returns: Sequence[float],
    *,
    annualization_factor: float = 252.0,
) -> float:
    series = pd.Series(list(returns), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2:
        return 0.0
    downside = series[series < 0]
    downside_std = float(np.sqrt(np.mean(np.square(downside)))) if len(downside) else 0.0
    if downside_std <= 0:
        return float("inf") if float(series.mean()) > 0 else 0.0
    return float(series.mean() / downside_std * math.sqrt(annualization_factor))


def compute_deflated_sharpe(
    daily_returns: Sequence[float],
    *,
    adjusted_sharpe: float,
    trial_count: int,
) -> Dict[str, float]:
    series = pd.Series(list(daily_returns), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2 or trial_count <= 0 or not np.isfinite(adjusted_sharpe):
        return {
            "deflated_sharpe_daily": np.nan,
            "deflated_sharpe_probability": np.nan,
            "deflated_sharpe_benchmark": np.nan,
            "deflated_sharpe_zscore": np.nan,
            "trial_count_formal": int(max(trial_count, 0)),
        }
    skew = float(series.skew()) if len(series) >= 3 else 0.0
    kurtosis = float(series.kurt()) + 3.0 if len(series) >= 4 else 3.0
    sr_std_term = 1.0 - skew * adjusted_sharpe + ((kurtosis - 1.0) / 4.0) * (adjusted_sharpe ** 2)
    sr_std_term = max(sr_std_term, 1e-12)
    sigma_sr = math.sqrt(sr_std_term / max(len(series) - 1, 1))
    if trial_count == 1:
        sr_benchmark = 0.0
    else:
        z1 = NORMAL_DIST.inv_cdf(1.0 - 1.0 / float(trial_count))
        z2 = NORMAL_DIST.inv_cdf(1.0 - 1.0 / (float(trial_count) * math.e))
        sr_benchmark = sigma_sr * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2)
    z_score = (adjusted_sharpe - sr_benchmark) / sigma_sr if sigma_sr > 0 else np.nan
    dsr_margin = float(adjusted_sharpe - sr_benchmark)
    dsr_probability = float(NORMAL_DIST.cdf(z_score)) if np.isfinite(z_score) else np.nan
    return {
        "deflated_sharpe_daily": dsr_margin,
        "deflated_sharpe_probability": dsr_probability,
        "deflated_sharpe_benchmark": float(sr_benchmark),
        "deflated_sharpe_zscore": float(z_score) if np.isfinite(z_score) else np.nan,
        "trial_count_formal": int(trial_count),
    }


def threshold_policy_trial_count(config: PipelineConfig) -> int:
    return int(len(config.p_min_grid) * len(config.theta_ev_grid) * len(config.theta_rel_grid))


def deterministic_seed_from_text(text: str) -> int:
    total = 0
    for idx, ch in enumerate(str(text), start=1):
        total = (total + idx * ord(ch)) % 2_147_483_647
    return int(total)


def build_stitched_policy_daily_frame(
    policy_daily_df: pd.DataFrame,
    *,
    starting_capital: float,
) -> pd.DataFrame:
    def _join_unique_strings(values: pd.Series) -> str:
        unique = [str(v) for v in pd.Series(values).dropna().astype(str).tolist() if str(v)]
        ordered: List[str] = []
        for value in unique:
            if value not in ordered:
                ordered.append(value)
        return "|".join(ordered)

    if len(policy_daily_df) == 0:
        return pd.DataFrame(
            columns=[
                "session_date_ny",
                "timestamp_utc",
                "daily_return",
                "equity",
                "active_positions_mean",
                "active_positions_p95",
                "active_positions_max",
                "active_exposure_mean",
                "fold",
                "max_concurrent",
                "fold_selected",
                "fold_skip_reason",
                "schema_version",
                "robustness_method_version",
                "search_family_definition_version",
                "implementation_status",
                "verification_stage_reached",
                "threshold_search_corrected",
                "full_pipeline_corrected",
                "trial_scope_formal",
                "trial_count_formal",
            ]
        )
    daily = policy_daily_df.copy()
    daily["session_date_ny"] = pd.to_datetime(daily["session_date_ny"]).dt.strftime("%Y-%m-%d")
    if "timestamp_utc" in daily.columns:
        daily["timestamp_utc"] = pd.to_datetime(daily["timestamp_utc"], utc=True, errors="coerce")
    sort_columns = ["session_date_ny"] + (["timestamp_utc"] if "timestamp_utc" in daily.columns else [])
    daily = daily.sort_values(sort_columns).reset_index(drop=True)
    if daily["session_date_ny"].duplicated().any():
        logging.info("Collapsing duplicate stitched session dates at fold boundaries into calendar-day returns.")
        agg_spec: Dict[str, Any] = {
            "daily_return": lambda s: float(np.prod(1.0 + pd.Series(s, dtype=float).fillna(0.0)) - 1.0),
            "active_positions_mean": "mean",
            "active_positions_p95": "max",
            "active_positions_max": "max",
            "active_exposure_mean": "mean",
            "fold": _join_unique_strings,
            "max_concurrent": "max",
            "fold_selected": "max",
            "fold_skip_reason": _join_unique_strings,
            "schema_version": "first",
            "robustness_method_version": "first",
            "search_family_definition_version": "first",
            "implementation_status": "first",
            "verification_stage_reached": "first",
            "threshold_search_corrected": "first",
            "full_pipeline_corrected": "first",
            "trial_scope_formal": "first",
            "trial_count_formal": "first",
        }
        available_agg = {column: spec for column, spec in agg_spec.items() if column in daily.columns}
        daily = daily.groupby("session_date_ny", as_index=False).agg(available_agg)
    returns = (
        daily["daily_return"].astype(float)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )
    daily["daily_return"] = returns
    daily["equity"] = float(starting_capital) * (1.0 + returns).cumprod()
    daily["timestamp_utc"] = pd.to_datetime(daily["session_date_ny"], utc=True)
    return daily


def summarize_stitched_policy_daily(
    policy_daily_df: pd.DataFrame,
    *,
    starting_capital: float,
    trial_count: int,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    daily = build_stitched_policy_daily_frame(policy_daily_df, starting_capital=starting_capital)
    if len(daily) == 0:
        empty = compute_daily_return_diagnostics([])
        dsr = compute_deflated_sharpe([], adjusted_sharpe=0.0, trial_count=trial_count)
        return daily, {
            **empty,
            **dsr,
            "stitched_daily_total_return": 0.0,
            "stitched_daily_cagr": 0.0,
            "stitched_daily_mdd": 0.0,
            "stitched_daily_calmar": 0.0,
            "avg_active_positions_daily": 0.0,
            "median_active_positions_daily": 0.0,
            "p95_active_positions_daily": 0.0,
            "flat_day_fraction": 1.0,
            "at_cap_day_fraction": 0.0,
            "avg_active_exposure_daily": 0.0,
        }
    daily_returns = daily["daily_return"].astype(float).tolist()
    diag = compute_daily_return_diagnostics(daily_returns)
    dsr = compute_deflated_sharpe(
        daily_returns,
        adjusted_sharpe=float(diag["adjusted_sharpe_daily"]),
        trial_count=trial_count,
    )
    equity = daily["equity"].astype(float)
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    mdd = abs(float(drawdown.min())) if len(drawdown) else 0.0
    cagr = annualized_cagr(
        float(starting_capital),
        float(equity.iloc[-1]),
        pd.Timestamp(str(daily["session_date_ny"].iloc[0])),
        pd.Timestamp(str(daily["session_date_ny"].iloc[-1])),
    ) if len(daily) else 0.0
    calmar = float(cagr / mdd) if mdd > 0 else 0.0
    active_positions = daily["active_positions_mean"].astype(float) if "active_positions_mean" in daily.columns else pd.Series(dtype=float)
    cap_series = (
        daily["max_concurrent"].astype(float)
        if "max_concurrent" in daily.columns
        else pd.Series([1.0] * len(daily), index=daily.index, dtype=float)
    )
    avg_active_positions_daily = float(active_positions.mean()) if len(active_positions) else 0.0
    median_active_positions_daily = float(active_positions.median()) if len(active_positions) else 0.0
    p95_active_positions_daily = float(np.quantile(active_positions, 0.95)) if len(active_positions) else 0.0
    flat_day_fraction = float((active_positions <= 0).mean()) if len(active_positions) else 1.0
    at_cap_day_fraction = float((active_positions >= cap_series).mean()) if len(active_positions) else 0.0
    avg_active_exposure_daily = float(daily["active_exposure_mean"].astype(float).mean()) if "active_exposure_mean" in daily.columns and len(daily) else 0.0
    return daily, {
        **diag,
        **dsr,
        "stitched_daily_total_return": float(equity.iloc[-1] / float(starting_capital) - 1.0) if len(equity) else 0.0,
        "stitched_daily_cagr": float(cagr),
        "stitched_daily_mdd": float(mdd),
        "stitched_daily_calmar": float(calmar),
        "avg_active_positions_daily": float(avg_active_positions_daily),
        "median_active_positions_daily": float(median_active_positions_daily),
        "p95_active_positions_daily": float(p95_active_positions_daily),
        "flat_day_fraction": float(flat_day_fraction),
        "at_cap_day_fraction": float(at_cap_day_fraction),
        "avg_active_exposure_daily": float(avg_active_exposure_daily),
    }


def evaluate_regime_diversity_policy(trades_df: pd.DataFrame) -> Dict[str, Any]:
    core_regimes = ("high_vol", "mid_vol", "low_vol")
    if len(trades_df) == 0 or "entry_regime_label" not in trades_df.columns or "pnl" not in trades_df.columns:
        return {
            "regime_diversity_policy_pass": False,
            "regime_diversity_policy_reason": "no_regime_trade_data",
            "regime_positive_count": 0,
            "top_regime_pnl_share": np.nan,
            "top_regime_label": "none",
        }
    pnl_by_regime = trades_df.groupby("entry_regime_label")["pnl"].sum()
    positive_pnl = pnl_by_regime.clip(lower=0.0)
    positive_total = float(positive_pnl.sum())
    if positive_total > 0:
        top_regime_label = str(positive_pnl.idxmax())
        top_regime_pnl_share = float(positive_pnl.max() / positive_total)
    else:
        top_regime_label = "none"
        top_regime_pnl_share = np.nan
    positive_count = int(sum(float(pnl_by_regime.get(regime, 0.0)) > 0 for regime in core_regimes))
    policy_pass = (
        np.isfinite(top_regime_pnl_share)
        and top_regime_pnl_share <= 0.60
        and positive_count >= 2
    )
    reasons: List[str] = []
    if not np.isfinite(top_regime_pnl_share):
        reasons.append("no_positive_regime_pnl")
    elif top_regime_pnl_share > 0.60:
        reasons.append("top_regime_share_gt_0.60")
    if positive_count < 2:
        reasons.append("fewer_than_two_positive_core_regimes")
    return {
        "regime_diversity_policy_pass": bool(policy_pass),
        "regime_diversity_policy_reason": "ok" if policy_pass else ";".join(reasons),
        "regime_positive_count": int(positive_count),
        "top_regime_pnl_share": float(top_regime_pnl_share) if np.isfinite(top_regime_pnl_share) else np.nan,
        "top_regime_label": top_regime_label,
    }


def evaluate_capacity_rule_compliance(trades_df: pd.DataFrame, config: PipelineConfig) -> Dict[str, Any]:
    if len(trades_df) == 0 or "participation_rate" not in trades_df.columns:
        return {
            "capacity_rule_compliant": True,
            "capacity_rule_violations": 0,
            "capacity_rule_violation_rate": 0.0,
        }
    participation = trades_df["participation_rate"].astype(float).replace([np.inf, -np.inf], np.nan)
    valid = participation.dropna()
    if len(valid) == 0:
        return {
            "capacity_rule_compliant": True,
            "capacity_rule_violations": 0,
            "capacity_rule_violation_rate": 0.0,
        }
    violations = int((valid > float(config.max_adv_participation) + 1e-12).sum())
    return {
        "capacity_rule_compliant": violations == 0,
        "capacity_rule_violations": int(violations),
        "capacity_rule_violation_rate": float(violations / len(valid)),
    }


def capacity_headroom_metrics(
    trades_df: pd.DataFrame,
    metrics: Mapping[str, Any],
    config: PipelineConfig,
) -> Dict[str, Any]:
    clipped = int(metrics.get("capacity_clipped_orders", 0) or 0)
    skipped = int(metrics.get("capacity_skipped_orders", 0) or 0)
    total_trades = int(metrics.get("n_trades", len(trades_df)) or 0)
    total_orders = max(total_trades + skipped, 1)
    clipped_or_skipped_fraction = float((clipped + skipped) / total_orders)
    gross_alpha = float(
        trades_df["pnl"].clip(lower=0.0).sum() if len(trades_df) and "pnl" in trades_df.columns else 0.0
    )
    capacity_drag = float(metrics.get("capacity_clipped_pnl_drag", 0.0) or 0.0)
    capacity_drag_fraction = float(capacity_drag / gross_alpha) if gross_alpha > 1e-12 else 0.0
    p95_participation = float(metrics.get("p95_participation_rate", 0.0) or 0.0)
    return {
        "clipped_or_skipped_order_fraction": clipped_or_skipped_fraction,
        "capacity_drag_fraction_of_gross_alpha": capacity_drag_fraction,
        "capacity_headroom_pass": bool(
            p95_participation <= float(config.headroom_adv_participation)
            and clipped_or_skipped_fraction <= float(config.max_clipped_or_skipped_order_fraction)
            and capacity_drag_fraction <= float(config.max_capacity_drag_fraction_live)
        ),
    }


def evaluate_scorecard_defaults(
    metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    adjusted_sharpe = float(metrics.get("adjusted_sharpe_daily", 0.0) or 0.0)
    profit_factor = float(metrics.get("profit_factor", 0.0) or 0.0)
    sortino = float(metrics.get("sortino_daily", 0.0) or 0.0)
    calmar = float(metrics.get("stitched_daily_calmar", metrics.get("calmar", 0.0)) or 0.0)
    max_drawdown = float(metrics.get("stitched_daily_mdd", metrics.get("mdd", 0.0)) or 0.0)
    dsr = float(metrics.get("deflated_sharpe_daily", -1.0) or -1.0)
    gross_edge_to_cost = float(metrics.get("gross_edge_to_round_trip_cost", 0.0) or 0.0)
    closed_trades = int(metrics.get("n_trades", 0) or 0)
    nonzero_days = int(metrics.get("n_nonzero_return_days", 0) or 0)
    positive_fold_fraction = float(metrics.get("positive_fold_fraction", 0.0) or 0.0)
    positive_regimes = int(metrics.get("regime_positive_count", 0) or 0)
    top_regime_share = float(metrics.get("top_regime_pnl_share", np.nan))
    capacity_headroom_pass = bool(metrics.get("capacity_headroom_pass", False))
    calendar_days = int(metrics.get("n_daily_observations", 0) or 0)
    research_viable = bool(
        adjusted_sharpe >= 0.75
        and profit_factor >= 1.20
        and sortino >= 1.00
        and calmar >= 0.50
        and max_drawdown <= 0.25
        and dsr > 0.0
        and gross_edge_to_cost >= 2.0
        and closed_trades >= 100
        and nonzero_days >= 100
        and positive_fold_fraction >= 0.60
        and calendar_days >= 126
    )
    live_pilot_viable = bool(
        adjusted_sharpe >= 1.00
        and profit_factor >= 1.25
        and sortino >= 1.50
        and calmar >= 0.75
        and max_drawdown <= 0.20
        and dsr > 0.0
        and gross_edge_to_cost >= 3.0
        and closed_trades >= 150
        and nonzero_days >= 150
        and positive_fold_fraction >= 0.60
        and positive_regimes >= 2
        and (not np.isfinite(top_regime_share) or top_regime_share <= 0.60)
        and calendar_days >= 252
        and capacity_headroom_pass
    )
    allocation_ready = bool(
        adjusted_sharpe >= 1.25
        and profit_factor >= 1.40
        and sortino >= 1.75
        and calmar >= 1.00
        and max_drawdown <= 0.15
        and dsr > 0.0
        and gross_edge_to_cost >= 4.0
        and closed_trades >= 250
        and nonzero_days >= 250
        and positive_fold_fraction >= 0.67
        and calendar_days >= 504
        and capacity_headroom_pass
    )
    return {
        "scorecard_label": SCORECARD_LABEL,
        "scorecard_archetype": SCORECARD_ARCHETYPE,
        "research_viable": research_viable,
        "live_pilot_viable": live_pilot_viable,
        "allocation_ready": allocation_ready,
    }


def _stage_implied_status(stage: str, *, deterministic_mode: bool) -> str:
    stage_text = str(stage or "code_present")
    if stage_text == "canonical_rerun_match":
        return "reproducible_verified" if deterministic_mode else "unit_tested"
    if stage_text.startswith("smoke_tier_"):
        try:
            tier = int(stage_text.rsplit("_", 1)[-1])
        except ValueError:
            tier = 0
        return "smoke_validated" if tier >= 2 else "unit_tested"
    if stage_text == "unit_tests":
        return "unit_tested"
    return "present"


def _default_stage_for_status(status: str) -> str:
    if status == "reproducible_verified":
        return "canonical_rerun_match"
    if status == "smoke_validated":
        return "smoke_tier_2"
    if status == "unit_tested":
        return "unit_tests"
    return "code_present"


def normalize_implementation_claim(
    requested_status: str,
    requested_stage: str,
    *,
    deterministic_mode: bool,
) -> Tuple[str, str]:
    status = requested_status if requested_status in IMPLEMENTATION_STATUS_VALUES else "present"
    stage = str(requested_stage or "code_present")
    implied_status = _stage_implied_status(stage, deterministic_mode=deterministic_mode)
    if verification_rank(status) > verification_rank(implied_status):
        status = implied_status
        stage = _default_stage_for_status(status)
    elif verification_rank(_stage_implied_status(stage, deterministic_mode=deterministic_mode)) > verification_rank(status):
        stage = _default_stage_for_status(status)
    return status, stage


def moving_block_bootstrap_white_reality_check(
    return_matrix: np.ndarray,
    *,
    block_length: int,
    bootstrap_reps: int,
    random_seed: int,
) -> Dict[str, float]:
    matrix = np.asarray(return_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        return {"wrc_pvalue": np.nan, "observed_best_mean": np.nan, "bootstrap_reps": int(bootstrap_reps)}
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    obs_stat = float(np.max(matrix.mean(axis=0)))
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    rng = np.random.default_rng(random_seed)
    length = matrix.shape[0]
    block = max(1, min(int(block_length), length))
    boot_stats: List[float] = []
    for _ in range(int(max(bootstrap_reps, 1))):
        starts = rng.integers(0, length, size=int(math.ceil(length / block)))
        idx: List[int] = []
        for start in starts.tolist():
            idx.extend(((start + np.arange(block)) % length).tolist())
        sample = centered[np.asarray(idx[:length], dtype=int)]
        boot_stats.append(float(np.max(sample.mean(axis=0))))
    pvalue = float((1 + sum(1 for stat in boot_stats if stat >= obs_stat)) / (len(boot_stats) + 1))
    return {
        "wrc_pvalue": pvalue,
        "observed_best_mean": obs_stat,
        "bootstrap_reps": int(len(boot_stats)),
    }


def infer_regime_label(frame: pd.DataFrame) -> pd.Series:
    if "vol_cluster_high_34" not in frame.columns or "vol_cluster_low_34" not in frame.columns:
        return pd.Series(["unknown"] * len(frame), index=frame.index)
    high = frame["vol_cluster_high_34"].astype(float) >= 0.5
    low = frame["vol_cluster_low_34"].astype(float) >= 0.5
    regime = np.where(high, "high_vol", np.where(low, "low_vol", "mid_vol"))
    return pd.Series(regime, index=frame.index)


def _serialize_bucket_positive_rates(values: Sequence[float]) -> str:
    serialized: List[Optional[float]] = []
    for value in values:
        numeric = float(value)
        serialized.append(numeric if np.isfinite(numeric) else None)
    return json.dumps(serialized)


def _deserialize_bucket_positive_rates(raw: object) -> Optional[List[float]]:
    if raw is None:
        return None
    if isinstance(raw, float) and np.isnan(raw):
        return None
    parsed: object = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, list):
        return None
    values: List[float] = []
    for item in parsed:
        if item is None or item == "":
            values.append(np.nan)
            continue
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            return None
    return values or None


def _aligned_spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return np.nan
    left_series = pd.Series(left, dtype=float)
    right_series = pd.Series(right, dtype=float)
    valid = left_series.notna() & right_series.notna()
    if int(valid.sum()) < 2:
        return np.nan
    corr = left_series.loc[valid].corr(right_series.loc[valid], method="spearman")
    return float(corr) if corr is not None and np.isfinite(corr) else np.nan


def apply_empirical_probability_map(
    reference_scored: pd.DataFrame,
    target_scored: pd.DataFrame,
    config: PipelineConfig,
    *,
    previous_bucket_positive_rates: Optional[Sequence[float]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    reward_r = config.target_atr_multiple / max(config.stop_atr_multiple, 1e-12)
    ref = reference_scored.copy()
    tgt = target_scored.copy()
    meta: Dict[str, Any] = {
        "empirical_prob_map_status": "deterministic_simple_rank_fallback",
        "empirical_prob_map_support_rows": 0,
        "empirical_prob_map_unique_scores": 0,
        "ranking_map_fit_samples": 0,
        "ranking_map_bucket_samples": "",
        "ranking_map_bucket_positive_rates": "[]",
        "ranking_map_adjacent_fold_spearman": np.nan,
        "ranking_map_adjacent_fold_spearman_evaluable": False,
        "ranking_map_fallback_usage_fraction": 1.0,
        "ranking_map_stability_pass": False,
        "ranking_map_top_2_buckets_positive_fraction": np.nan,
        "ranking_map_max_fallback_usage_fraction_allowed": float(config.empirical_prob_map_max_fallback_usage_fraction),
        "ranking_map_min_adjacent_fold_spearman_allowed": float(config.empirical_prob_map_min_adjacent_fold_spearman),
        "ranking_map_guardrails_pass": False,
        "ranking_map_guardrail_failure_reasons": "",
    }
    valid = ref[["p_cal", "long_win"]].replace([np.inf, -np.inf], np.nan).dropna()
    meta["empirical_prob_map_support_rows"] = int(len(valid))
    meta["empirical_prob_map_unique_scores"] = int(valid["p_cal"].nunique()) if len(valid) else 0
    meta["ranking_map_fit_samples"] = int(len(valid))

    def _simple_rank_predict(values: pd.Series) -> np.ndarray:
        if len(valid) == 0:
            return clip_prob(pd.Series(values).astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.5).to_numpy())
        fit_scores = np.sort(valid["p_cal"].astype(float).to_numpy())
        raw = pd.Series(values).astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.5).to_numpy()
        probs = np.searchsorted(fit_scores, raw, side="right") / max(len(fit_scores), 1)
        return clip_prob(np.asarray(probs, dtype=float))

    bucket_samples: List[int] = []
    bucket_positive_rates: List[float] = []
    top_two_positive_fraction = np.nan
    if len(valid) >= max(config.empirical_prob_map_buckets, 1):
        pct_rank = valid["p_cal"].rank(method="average", pct=True)
        valid_bucket = np.ceil(pct_rank * config.empirical_prob_map_buckets).clip(1, config.empirical_prob_map_buckets).astype(int)
        bucket_summary = (
            valid.assign(bucket=valid_bucket)
            .groupby("bucket")
            .agg(samples=("long_win", "size"), positive_rate=("long_win", "mean"))
            .reindex(range(1, config.empirical_prob_map_buckets + 1))
        )
        bucket_samples = bucket_summary["samples"].fillna(0).astype(int).tolist()
        bucket_positive_rates = [
            float(value) if pd.notna(value) else np.nan
            for value in bucket_summary["positive_rate"].tolist()
        ]
        top_two = bucket_summary["positive_rate"].dropna().tail(2)
        if len(top_two):
            top_two_positive_fraction = float((top_two > 0.5).mean())
    meta["ranking_map_bucket_samples"] = json.dumps(bucket_samples)
    meta["ranking_map_bucket_positive_rates"] = _serialize_bucket_positive_rates(bucket_positive_rates)
    meta["ranking_map_top_2_buckets_positive_fraction"] = top_two_positive_fraction
    adjacent_fold_spearman = np.nan
    if previous_bucket_positive_rates is not None and bucket_positive_rates:
        adjacent_fold_spearman = _aligned_spearman(previous_bucket_positive_rates, bucket_positive_rates)
    meta["ranking_map_adjacent_fold_spearman"] = adjacent_fold_spearman
    meta["ranking_map_adjacent_fold_spearman_evaluable"] = bool(np.isfinite(adjacent_fold_spearman))
    enough_bucket_support = bool(bucket_samples) and all(sample >= config.empirical_prob_map_min_bucket_rows for sample in bucket_samples if sample > 0)

    if (
        len(valid) >= config.empirical_prob_map_min_rows
        and valid["long_win"].nunique() >= 2
        and valid["p_cal"].nunique() >= 10
        and enough_bucket_support
        and np.isfinite(top_two_positive_fraction)
        and top_two_positive_fraction >= config.empirical_prob_map_min_top_bucket_positive_fraction
    ):
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(valid["p_cal"].astype(float), valid["long_win"].astype(float))

        def _predict_prob(values: pd.Series) -> np.ndarray:
            clipped = pd.Series(values).astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.5)
            return clip_prob(np.asarray(iso.predict(clipped), dtype=float))

        meta["empirical_prob_map_status"] = "isotonic"
        meta["ranking_map_fallback_usage_fraction"] = 0.0
    else:
        _predict_prob = _simple_rank_predict

    guardrail_failures: List[str] = []
    if float(meta["ranking_map_fallback_usage_fraction"]) > float(meta["ranking_map_max_fallback_usage_fraction_allowed"]) + 1e-12:
        guardrail_failures.append("fallback_usage_fraction_exceeds_max")
    if bool(meta["ranking_map_adjacent_fold_spearman_evaluable"]):
        observed_spearman = float(meta["ranking_map_adjacent_fold_spearman"])
        if observed_spearman + 1e-12 < float(meta["ranking_map_min_adjacent_fold_spearman_allowed"]):
            guardrail_failures.append("adjacent_fold_spearman_below_min")
    meta["ranking_map_guardrails_pass"] = len(guardrail_failures) == 0
    meta["ranking_map_guardrail_failure_reasons"] = "ok" if not guardrail_failures else ";".join(guardrail_failures)
    meta["ranking_map_stability_pass"] = bool(
        meta["empirical_prob_map_status"] == "isotonic" and meta["ranking_map_guardrails_pass"]
    )

    for frame in (ref, tgt):
        frame["p_empirical"] = _predict_prob(frame["p_cal"])
        frame["ev_empirical_r"] = frame["p_empirical"] * reward_r - (1.0 - frame["p_empirical"]) - frame["cost_est_r"].astype(float)
        frame["entry_regime_label"] = infer_regime_label(frame)
        frame["empirical_prob_map_status"] = str(meta["empirical_prob_map_status"])
        frame["empirical_prob_map_support_rows"] = int(meta["empirical_prob_map_support_rows"])
        frame["ranking_map_fit_samples"] = int(meta["ranking_map_fit_samples"])
        frame["ranking_map_bucket_samples"] = str(meta["ranking_map_bucket_samples"])
        frame["ranking_map_bucket_positive_rates"] = str(meta["ranking_map_bucket_positive_rates"])
        frame["ranking_map_adjacent_fold_spearman"] = meta["ranking_map_adjacent_fold_spearman"]
        frame["ranking_map_adjacent_fold_spearman_evaluable"] = bool(meta["ranking_map_adjacent_fold_spearman_evaluable"])
        frame["ranking_map_fallback_usage_fraction"] = float(meta["ranking_map_fallback_usage_fraction"])
        frame["ranking_map_max_fallback_usage_fraction_allowed"] = float(meta["ranking_map_max_fallback_usage_fraction_allowed"])
        frame["ranking_map_min_adjacent_fold_spearman_allowed"] = float(meta["ranking_map_min_adjacent_fold_spearman_allowed"])
        frame["ranking_map_guardrails_pass"] = bool(meta["ranking_map_guardrails_pass"])
        frame["ranking_map_guardrail_failure_reasons"] = str(meta["ranking_map_guardrail_failure_reasons"])
        frame["ranking_map_stability_pass"] = bool(meta["ranking_map_stability_pass"])
    return ref, tgt, meta


def sanitize_for_json(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        x = float(obj)
        return x if np.isfinite(x) else None
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return str(obj)
    return obj


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_code_fingerprint() -> str:
    repo_root = Path(__file__).resolve().parent
    roots = [
        Path(__file__).resolve(),
        repo_root / "docs" / "phase1-research-spec.md",
        repo_root / "docs" / "phase1-execution-roadmap.md",
    ]
    digest = hashlib.sha256()
    for path in roots:
        if not path.exists():
            raise FileNotFoundError(f"Missing fingerprint input: {path}")
        digest.update(str(path.as_posix()).encode("utf-8"))
        digest.update(file_sha256(path).encode("utf-8"))
    return digest.hexdigest()


def build_input_data_hash(path: Path) -> str:
    return file_sha256(path)


def load_input_build_metadata(path: Path) -> Dict[str, Any]:
    manifest_path = Path(str(path) + ".manifest.json")
    metadata: Dict[str, Any] = {
        "input_panel_manifest_path": str(manifest_path) if manifest_path.exists() else None,
        "input_panel_manifest_present": manifest_path.exists(),
        "input_panel_manifest_version": None,
        "input_panel_contract_name": None,
        "input_panel_content_hash": None,
        "dataset_build_id": None,
        "export_panel_version_id": None,
    }
    if not manifest_path.exists():
        return metadata
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return metadata
    metadata.update(
        {
            "input_panel_manifest_version": payload.get("manifest_version"),
            "input_panel_contract_name": payload.get("contract_name"),
            "input_panel_content_hash": payload.get("content_hash"),
            "dataset_build_id": payload.get("dataset_build_id"),
            "export_panel_version_id": payload.get("export_panel_version_id"),
        }
    )
    return metadata


def require_input_build_metadata(path: Path, metadata: Mapping[str, Any]) -> None:
    if not metadata.get("input_panel_manifest_present"):
        raise RuntimeError(
            f"Input panel manifest is required for {path}. "
            "Use the canonical export bridge so the panel carries dataset_build_id and export_panel_version_id."
        )
    missing = [
        field
        for field in ("dataset_build_id", "export_panel_version_id")
        if not metadata.get(field)
    ]
    if missing:
        raise RuntimeError(
            f"Input panel manifest for {path} is missing required build references: {missing}"
        )


def build_feature_set_version(features: Sequence[str]) -> str:
    normalized = "|".join(sorted({str(feature) for feature in features}))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"feature_set::{digest}"


def maybe_log_mlflow_summary(
    *,
    config: PipelineConfig,
    input_path: Path,
    paths: OutputPaths,
    config_snapshot_payload: Mapping[str, Any],
    overall_metrics: Mapping[str, Any],
    fold_metrics_df: pd.DataFrame,
) -> None:
    try:
        from mlflow_integration.tracking import (
            log_aggregate_metrics,
            log_artifact_path,
            log_dataset,
            log_fold_metrics,
            pipeline_run_context,
        )
    except Exception as exc:  # pragma: no cover - optional dependency surface
        logging.info("MLflow tracking unavailable: %s", exc)
        return

    extra_tags = {
        "dataset_build_id": config_snapshot_payload.get("dataset_build_id"),
        "export_panel_version_id": config_snapshot_payload.get("export_panel_version_id"),
        "feature_set_version": config_snapshot_payload.get("feature_set_version"),
        "input_panel_manifest_present": config_snapshot_payload.get("input_panel_manifest_present"),
    }
    extra_params = {
        "dataset_build_id": config_snapshot_payload.get("dataset_build_id"),
        "export_panel_version_id": config_snapshot_payload.get("export_panel_version_id"),
        "feature_set_version": config_snapshot_payload.get("feature_set_version"),
        "input_panel_manifest_present": config_snapshot_payload.get("input_panel_manifest_present"),
        "input_panel_manifest_path": config_snapshot_payload.get("input_panel_manifest_path"),
        "input_panel_manifest_version": config_snapshot_payload.get("input_panel_manifest_version"),
        "input_panel_contract_name": config_snapshot_payload.get("input_panel_contract_name"),
        "effective_cost_model": config_snapshot_payload.get("effective_cost_model"),
        "verification_artifact_path": str(paths.state_dir / "verification.json"),
        "config_snapshot_path": str(paths.state_dir / "config_snapshot.json"),
        "overall_metrics_path": str(paths.metrics_dir / "overall_metrics.json"),
        "selected_model_artifact_path": str(paths.strategies_dir / "best_strategy_summary.json"),
        "audit_plot_path": str(paths.reports_dir / "equity_curve_best_concurrency.png"),
        "report_path": str(paths.reports_dir / "final_report.md"),
    }

    panel_digest = config_snapshot_payload.get("input_panel_content_hash") or config_snapshot_payload.get(
        "input_data_hash"
    )
    manifest_path = config_snapshot_payload.get("input_panel_manifest_path")

    with pipeline_run_context(config, extra_tags=extra_tags, extra_params=extra_params):
        log_dataset("input_panel_csv", str(input_path), digest=str(panel_digest) if panel_digest else None)
        if manifest_path:
            log_dataset("input_panel_manifest", str(manifest_path))
        for _, row in fold_metrics_df.iterrows():
            fold_name = str(row.get("fold", "unknown_fold"))
            log_fold_metrics(fold_name, row.to_dict())
        log_aggregate_metrics(dict(overall_metrics))
        for artifact_path in (
            paths.state_dir / "verification.json",
            paths.state_dir / "config_snapshot.json",
            paths.metrics_dir / "overall_metrics.json",
            paths.strategies_dir / "best_strategy_summary.json",
            paths.reports_dir / "final_report.md",
            paths.reports_dir / "equity_curve_best_concurrency.png",
        ):
            log_artifact_path(str(artifact_path))


def run_pipeline_with_optional_lineage(config: PipelineConfig) -> Dict[str, object]:
    output_dir = _resolve_project_path(config.output_dir, force_project_drive=True)
    input_path = _resolve_project_path(config.input_panel_csv)
    paths = build_output_paths(output_dir)
    input_build_metadata = load_input_build_metadata(input_path)

    try:
        from lineage import PipelineLineageEmitter
        from lineage.facets import (
            build_references_dataset_facet,
            dataset_schema_facet,
            pipeline_config_facet,
        )
    except Exception as exc:  # pragma: no cover - optional dependency surface
        logging.info("OpenLineage unavailable: %s", exc)
        return run_pipeline(config)

    try:
        emitter = PipelineLineageEmitter(output_dir=str(paths.state_dir / "lineage_events"))
    except Exception as exc:  # pragma: no cover - optional dependency surface
        logging.info("OpenLineage emitter unavailable: %s", exc)
        return run_pipeline(config)

    lineage_run_id = str(uuid.uuid4())
    emitter_instance: Any | None = emitter
    try:
        input_datasets: List[Dict[str, Any]] = [
            {
                "namespace": "file",
                "name": str(input_path),
                "facets": {
                    **dataset_schema_facet(
                        [
                            "ticker",
                            "timestamp_utc",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "is_incomplete_session",
                        ],
                        {
                            "ticker": "string",
                            "timestamp_utc": "datetime",
                            "open": "float64",
                            "high": "float64",
                            "low": "float64",
                            "close": "float64",
                            "volume": "float64",
                            "is_incomplete_session": "boolean",
                        },
                    ),
                    **build_references_dataset_facet(
                        dataset_build_id=cast(Optional[str], input_build_metadata.get("dataset_build_id")),
                        export_panel_version_id=cast(
                            Optional[str], input_build_metadata.get("export_panel_version_id")
                        ),
                        content_hash=cast(Optional[str], input_build_metadata.get("input_panel_content_hash")),
                        contract_name=cast(Optional[str], input_build_metadata.get("input_panel_contract_name")),
                        manifest_path=cast(Optional[str], input_build_metadata.get("input_panel_manifest_path")),
                        output_path=str(input_path),
                    ),
                },
            }
        ]
        manifest_path = input_build_metadata.get("input_panel_manifest_path")
        if manifest_path:
            input_datasets.append(
                {
                    "namespace": "file",
                    "name": str(manifest_path),
                    "facets": build_references_dataset_facet(
                        dataset_build_id=cast(Optional[str], input_build_metadata.get("dataset_build_id")),
                        export_panel_version_id=cast(
                            Optional[str], input_build_metadata.get("export_panel_version_id")
                        ),
                        content_hash=cast(Optional[str], input_build_metadata.get("input_panel_content_hash")),
                        contract_name=cast(Optional[str], input_build_metadata.get("input_panel_contract_name")),
                        manifest_path=str(manifest_path),
                        output_path=str(input_path),
                    ),
                }
            )
        emitter_instance.emit_start(
            lineage_run_id,
            input_datasets,
            config_facet=pipeline_config_facet(
                {
                    "schema_version": SCHEMA_VERSION,
                    "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
                    "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
                    "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
                    "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
                    "trial_scope_formal": TRIAL_SCOPE_FORMAL,
                    "input_panel_csv": str(input_path),
                    "output_dir": str(output_dir),
                    "dataset_build_id": input_build_metadata.get("dataset_build_id"),
                    "export_panel_version_id": input_build_metadata.get("export_panel_version_id"),
                }
            ),
        )
    except Exception as exc:  # pragma: no cover - optional dependency surface
        logging.info("OpenLineage start emission failed: %s", exc)
        emitter_instance = None

    try:
        summary = run_pipeline(config)
    except Exception as exc:
        if emitter_instance is not None:
            try:
                emitter_instance.emit_fail(lineage_run_id, str(exc))
            except Exception as emit_exc:  # pragma: no cover - optional dependency surface
                logging.info("OpenLineage fail emission failed: %s", emit_exc)
        raise

    if emitter_instance is not None:
        dataset_build_id = cast(Optional[str], summary.get("dataset_build_id")) or cast(
            Optional[str], input_build_metadata.get("dataset_build_id")
        )
        export_panel_version_id = cast(Optional[str], summary.get("export_panel_version_id")) or cast(
            Optional[str], input_build_metadata.get("export_panel_version_id")
        )
        output_specs: List[tuple[Path, str | None]] = [
            (paths.state_dir / "config_snapshot.json", None),
            (paths.state_dir / "verification.json", None),
            (paths.metrics_dir / "overall_metrics.json", None),
            (paths.strategies_dir / "best_strategy_summary.json", None),
            (paths.reports_dir / "final_report.md", None),
        ]
        output_datasets = [
            {
                "namespace": "file",
                "name": str(path),
                "facets": build_references_dataset_facet(
                    dataset_build_id=dataset_build_id,
                    export_panel_version_id=export_panel_version_id,
                    manifest_path=manifest_path,
                    output_path=str(path),
                ),
            }
            for path, _ in output_specs
            if path.exists()
        ]
        try:
            emitter_instance.emit_complete(lineage_run_id, output_datasets)
        except Exception as exc:  # pragma: no cover - optional dependency surface
            logging.info("OpenLineage complete emission failed: %s", exc)
        atomic_write_json(
            paths.state_dir / "lineage_summary.json",
            {
                "lineage_run_id": lineage_run_id,
                "lineage_event_dir": str(paths.state_dir / "lineage_events"),
                "dataset_build_id": dataset_build_id,
                "export_panel_version_id": export_panel_version_id,
                "input_panel_manifest_path": manifest_path,
            },
        )
        summary["lineage_run_id"] = lineage_run_id
        summary["lineage_event_dir"] = str(paths.state_dir / "lineage_events")
    return summary


def build_config_hash(config: PipelineConfig) -> str:
    payload = sanitize_for_json(asdict(config))
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def effective_cost_model(config: PipelineConfig) -> Dict[str, Any]:
    return {
        "commission_per_side": float(config.commission_per_side),
        "slippage_per_side": float(config.slippage_per_fill),
        "spread_source": str(config.spread_source),
        "borrow_or_financing_rate": float(config.overnight_brokerage),
        "reject_or_clip_penalty": str(config.reject_or_clip_penalty),
        "idle_cash_treatment": str(config.idle_cash_treatment),
    }


def validate_cost_model(config: PipelineConfig) -> Tuple[bool, List[str], Dict[str, Any]]:
    model = effective_cost_model(config)
    required = [
        "commission_per_side",
        "slippage_per_side",
        "spread_source",
        "borrow_or_financing_rate",
        "reject_or_clip_penalty",
        "idle_cash_treatment",
    ]
    missing = [field for field in required if field not in model or model[field] in (None, "")]
    return len(missing) == 0, missing, model


def verification_rank(status: str) -> int:
    try:
        return IMPLEMENTATION_STATUS_VALUES.index(status)
    except ValueError:
        return -1


def build_resume_fingerprint(config: PipelineConfig) -> Dict[str, Any]:
    fingerprint = sanitize_for_json({k: v for k, v in asdict(config).items() if k not in {"resume", "output_dir"}})
    assert isinstance(fingerprint, dict)
    fingerprint.update(
        {
            "schema_version": SCHEMA_VERSION,
            "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
            "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
            "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
            "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
            "trial_scope_formal": TRIAL_SCOPE_FORMAL,
            "scorecard_label": SCORECARD_LABEL,
            "scorecard_archetype": SCORECARD_ARCHETYPE,
            "code_fingerprint": build_code_fingerprint(),
        }
    )
    return cast(Dict[str, Any], fingerprint)


def classification_diagnostics(y_true: pd.Series, p_pred: pd.Series) -> Dict[str, float]:
    y = pd.Series(y_true).astype(int).values
    p = clip_prob(pd.Series(p_pred).astype(float).values)
    out = {
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(np.mean((p - y) ** 2)),
    }
    if len(np.unique(y)) == 2:
        out["roc_auc"] = float(roc_auc_score(y, p))
        out["pr_auc"] = float(average_precision_score(y, p))
    else:
        out["roc_auc"] = np.nan
        out["pr_auc"] = np.nan
    return out


def spearman_ic(scores: pd.Series, outcome: pd.Series, min_n: int = 5) -> Dict[str, float]:
    """Compute pooled Spearman rank IC (single correlation over all pairs).
    For timestamp-level cross-sectional IC, use spearman_ic_by_timestamp."""
    s = pd.Series(scores).astype(float)
    o = pd.Series(outcome).astype(float)
    valid = s.notna() & o.notna()
    s, o = s[valid], o[valid]
    if len(s) < min_n:
        return {
            "spearman_ic": np.nan,
            "ic_std": np.nan,
            "ic_hit_rate": np.nan,
            "icir": np.nan,
            "n_pairs": int(len(s)),
        }
    ic = float(s.corr(o, method="spearman"))
    return {
        "spearman_ic": ic,
        "ic_std": np.nan,
        "ic_hit_rate": 1.0 if ic > 0 else 0.0,
        "icir": np.nan if not np.isfinite(ic) else ic,
        "n_pairs": int(len(s)),
    }


def benchmark_base_rate_metrics(y_true: pd.Series, y_train: pd.Series) -> Dict[str, float]:
    """Base-rate predictor metrics: constant p = train positive prevalence. Used as sanity gate."""
    y = pd.Series(y_true).astype(int).values
    p_base = float(pd.Series(y_train).astype(int).mean())
    p = np.full(len(y), p_base, dtype=float)

    out = {
        "benchmark_log_loss": float(log_loss(y, clip_prob(p), labels=[0, 1])),
        "benchmark_brier": float(np.mean((p - y) ** 2)),
    }
    if len(np.unique(y)) == 2:
        out["benchmark_roc_auc"] = float(roc_auc_score(y, p))
        out["benchmark_pr_auc"] = float(average_precision_score(y, p))
    else:
        out["benchmark_roc_auc"] = np.nan
        out["benchmark_pr_auc"] = np.nan
    return out


def variance_ratio(series: pd.Series, lag: int = 5, window: int = 50) -> pd.Series:
    r = series.fillna(0.0)
    diff1 = r.diff(1)
    difflag = r.diff(lag)
    var1 = diff1.rolling(window).var()
    varlag = difflag.rolling(window).var()
    return varlag / (lag * var1).replace(0, np.nan)


def binary_entropy(p: pd.Series) -> pd.Series:
    p = p.clip(1e-6, 1 - 1e-6)
    return -(p * np.log(p) + (1 - p) * np.log(1 - p)) / np.log(2)


def frac_weights(d: float, size: int) -> np.ndarray:
    w = [1.0]
    for k in range(1, size):
        w.append(-w[-1] * (d - k + 1) / k)
    return np.array(w)


FRAC_W = frac_weights(0.35, 50)


def fracret(series: pd.Series, weights: np.ndarray = FRAC_W) -> pd.Series:
    x = series.fillna(0.0).values.astype(float)
    w = weights[::-1]
    out = np.full(len(x), np.nan)
    m = len(w)
    for i in range(m - 1, len(x)):
        out[i] = np.dot(x[i - m + 1 : i + 1], w)
    return pd.Series(out, index=series.index)


# ============================================================
# DATA LOADING / VERIFICATION
# ============================================================
def verify_panel(df: pd.DataFrame) -> Dict[str, object]:
    required = {
        "ticker", "timestamp_utc", "open", "high", "low", "close", "volume", "is_incomplete_session"
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Panel missing required columns: {missing}")
    duplicate_rows = int(df.duplicated(subset=["ticker", "timestamp_utc"]).sum())
    # Per-ticker monotonicity (panel is typically passed after load_panel, which sorts by ticker, timestamp).
    monotonic_violations = 0
    for _, g in df.groupby("ticker"):
        if not g["timestamp_utc"].is_monotonic_increasing:
            monotonic_violations += 1
    ohlc_bad = int(
        ((df["low"] > df[["open", "close", "high"]].min(axis=1))
         | (df["high"] < df[["open", "close", "low"]].max(axis=1))).sum()
    )
    regularity = verify_panel_timestamp_regularity(df)
    per_ticker_df = regularity.get("per_ticker")
    per_ticker_coverage: List[Dict[str, object]] = []
    if isinstance(per_ticker_df, pd.DataFrame) and not per_ticker_df.empty:
        per_ticker_coverage = per_ticker_df.to_dict(orient="records")
    return {
        "rows": int(len(df)),
        "tickers": sorted(df["ticker"].unique().tolist()),
        "start_utc": str(df["timestamp_utc"].min()),
        "end_utc": str(df["timestamp_utc"].max()),
        "duplicate_ticker_timestamp_rows": duplicate_rows,
        "monotonic_violations": monotonic_violations,
        "ohlc_integrity_failures": ohlc_bad,
        "incomplete_session_rows": int(df["is_incomplete_session"].astype(bool).sum()),
        "optuna_available": OPTUNA_AVAILABLE,
        "panel_timestamp_regularity": {k: v for k, v in regularity.items() if k != "per_ticker"},
        "per_ticker_coverage": per_ticker_coverage,
    }


def load_panel(config: PipelineConfig) -> pd.DataFrame:
    path = Path(config.input_panel_csv)
    if not path.exists():
        raise FileNotFoundError(f"Input panel not found: {path}")
    df = pd.read_csv(path, parse_dates=["timestamp_utc"])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if "is_incomplete_session" in df.columns:
        # Handle "True"/"False" strings from CSV
        col = df["is_incomplete_session"]
        if col.dtype == object or col.dtype.name == "string":
            df["is_incomplete_session"] = col.astype(str).str.lower().isin(("true", "1", "yes"))
        else:
            df["is_incomplete_session"] = col.astype(bool)
    if "timestamp_ny" in df.columns:
        df["timestamp_ny"] = pd.to_datetime(df["timestamp_ny"], errors="coerce", utc=True)
    df = df.sort_values(["ticker", "timestamp_utc"]).reset_index(drop=True)
    return df


# ============================================================
# FEATURE ENGINEERING
# ============================================================
def build_feature_registry(features: Sequence[str]) -> pd.DataFrame:
    """Build a canonical feature registry for the features implemented in this file.

    This does not attempt to be a full parser of the markdown specs; instead it
    encodes the implemented subset explicitly and marks anything not present in
    the current feature list as unavailable. This keeps registry generation
    deterministic and auditable.
    """
    rows: List[Dict[str, Any]] = []

    def _row(
        feature_name: str,
        english_name: str,
        family: str,
        subfamily: str,
        regular_or_physics: str,
        lookback: Optional[int],
        formula_group: str,
        depends_on: Sequence[str],
        formula: str = "",
        timestamping_rule: str = "Computed with information available at or before bar close t; aligned to trade at t+1 open.",
        economic_thesis: str = "",
        expected_sign: str = "mixed",
        expected_decay_horizon: str = "",
        default_enabled: bool = True,
        implementation_status: str = "present",
        availability_status: str = "available",
        candidate_group_id: str = "",
        orthogonality_cluster_id: str = "",
        family_cap_weight: float = 1.0,
        interpretability_tag: str = "",
        requires_external_reference: bool = False,
        notes: str = "",
        disabled_reason: str = "",
    ) -> None:
        rows.append(
            {
                "feature_name": feature_name,
                "english_name": english_name,
                "family": family,
                "subfamily": subfamily,
                "regular_or_physics": regular_or_physics,
                "lookback": lookback,
                "formula": formula or english_name,
                "timestamping_rule": timestamping_rule,
                "economic_thesis": economic_thesis or f"{family} signal intended to explain multi-bar forward returns.",
                "expected_sign": expected_sign,
                "expected_decay_horizon": expected_decay_horizon or ("multi-day" if lookback is None else f"{lookback} bars"),
                "parameters": {},  # Reserved for formula params; not yet populated
                "formula_group": formula_group,
                "default_enabled": bool(default_enabled),
                "implementation_status": implementation_status,
                "availability_status": availability_status,
                "depends_on": list(depends_on),
                "candidate_group_id": candidate_group_id,
                "orthogonality_cluster_id": orthogonality_cluster_id,
                "family_cap_weight": float(family_cap_weight),
                "interpretability_tag": interpretability_tag,
                "requires_external_reference": bool(requires_external_reference),
                "notes": notes,
                "disabled_reason": disabled_reason,
            }
        )

    # Core return / momentum and volatility families (implemented subset).
    for n in (1, 3, 5, 10, 20):
        name = f"ret_{n}"
        _row(
            feature_name=name,
            english_name=f"{n}-bar simple return",
            family="returns_momentum",
            subfamily="simple_return",
            regular_or_physics="regular",
            lookback=n,
            formula_group="simple_return_n",
            depends_on=["close"],
            formula=f"close[t] / close[t-{n}] - 1",
            economic_thesis="Recent directional persistence can carry into the forward label horizon.",
            expected_sign="positive",
            default_enabled=True,
        )

    for name, english, lookback, formula_group in [
        ("roc_10", "10-bar rate-of-change", 10, "simple_return_n"),
        ("roc_20", "20-bar rate-of-change", 20, "simple_return_n"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="returns_momentum",
            subfamily="roc",
            regular_or_physics="regular",
            lookback=lookback,
            formula_group=formula_group,
            depends_on=["close"],
            formula=f"close[t] / close[t-{lookback}] - 1",
            economic_thesis="Rate-of-change captures intermediate momentum continuation.",
            expected_sign="positive",
        )

    for name, english, lookback in [
        ("ema_gap_10_20", "EMA(10) vs EMA(20) gap", 20),
        ("ema_gap_20_50", "EMA(20) vs EMA(50) gap", 50),
        ("price_vs_ema20", "Price vs EMA(20)", 20),
        ("price_vs_ema50", "Price vs EMA(50)", 50),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="trend_ma",
            subfamily="ema_gap",
            regular_or_physics="regular",
            lookback=lookback,
            formula_group="ema_gap",
            depends_on=["close"],
            formula=english,
            economic_thesis="Trend and moving-average displacement can proxy persistent directional pressure.",
            expected_sign="positive",
        )

    _row(
        feature_name="rsi_14",
        english_name="14-bar RSI (Wilder)",
        family="oscillator",
        subfamily="rsi",
        regular_or_physics="regular",
        lookback=14,
        formula_group="rsi_n",
        depends_on=["close"],
        formula="Wilder RSI over 14 bars",
        economic_thesis="Short-horizon momentum exhaustion or persistence may explain multi-bar forward returns.",
        expected_sign="mixed",
    )
    for name, english in [
        ("stoch_k_14_3", "Stochastic %K 14,3"),
        ("stoch_d_14_3", "Stochastic %D 14,3"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="oscillator",
            subfamily="stochastic",
            regular_or_physics="regular",
            lookback=14,
            formula_group="stoch_k_n_s",
            depends_on=["high", "low", "close"],
            formula=english,
            economic_thesis="Position within recent range may capture overextension or breakout persistence.",
            expected_sign="mixed",
        )

    for name, english in [
        ("macd_12_26_9", "MACD 12-26-9"),
        ("macd_signal_12_26_9", "MACD signal 12-26-9"),
        ("macd_hist_12_26_9", "MACD histogram 12-26-9"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="macd_ppo",
            subfamily="macd",
            regular_or_physics="regular",
            lookback=26,
            formula_group="macd_fast_slow_signal",
            depends_on=["close"],
            formula=english,
            economic_thesis="Trend acceleration and MACD structure can proxy persistent directional pressure.",
            expected_sign="positive",
        )

    # Volatility / range block (including context ladder).
    for name, english, lookback, formula_group in [
        ("atr_14", "ATR(14)", 14, "atr_n"),
        ("atr_pct_14", "ATR(14) as fraction of price", 14, "atr_pct_n"),
        ("range_pct_1", "1-bar high-low range as % of close", 1, "range_pct_n"),
        ("realized_vol_10", "Realized vol 10 bars", 10, "realized_vol_n"),
        ("realized_vol_20", "Realized vol 20 bars", 20, "realized_vol_n"),
        ("realized_vol_13", "Realized vol 13 bars", 13, "realized_vol_n"),
        ("realized_vol_34", "Realized vol 34 bars", 34, "realized_vol_n"),
        ("realized_vol_89", "Realized vol 89 bars", 89, "realized_vol_n"),
        ("vol_of_vol_20", "Vol of vol 20 bars", 20, "vol_of_vol_n"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="volatility_range",
            subfamily="realized_vol",
            regular_or_physics="regular",
            lookback=lookback,
            formula_group=formula_group,
            depends_on=["close"],
            formula=english,
            economic_thesis="Volatility and range context can shape forward payoff asymmetry and selectivity.",
            expected_sign="mixed",
        )

    # Volume / flow and cross-sectional context.
    for name, english, lookback, family, subfamily in [
        ("vol_z_20", "Volume z-score 20 bars", 20, "volume_flow", "volume_z"),
        ("rel_volume_20", "Relative volume 20 bars", 20, "volume_flow", "relative_volume"),
        ("obv", "On-balance volume", 0, "volume_flow", "obv"),
        ("obv_slope_5", "OBV slope over 5 bars", 5, "volume_flow", "obv"),
        ("cmf_20", "Chaikin Money Flow 20 bars", 20, "volume_flow", "cmf"),
        ("mfi_14", "Money Flow Index 14 bars", 14, "volume_flow", "mfi"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family=family,
            subfamily=subfamily,
            regular_or_physics="regular",
            lookback=lookback if lookback > 0 else None,
            formula_group=subfamily,
            depends_on=["high", "low", "close", "volume"],
            formula=english,
            economic_thesis="Volume and flow can proxy participation quality and continuation strength.",
            expected_sign="positive",
        )

    # Physics / regime features implemented here.
    for name, english, lookback, formula_group in [
        ("hurst_proxy_50", "Hurst proxy via variance ratio (50 bars)", 50, "variance_ratio_proxy"),
        ("entropy_sign_20", "Entropy of sign over 20 bars", 20, "entropy_sign"),
        ("autocorr_1_20", "Lag-1 autocorrelation over 20 bars", 20, "autocorr"),
        ("autocorr_5_20", "Lag-5 autocorrelation over 20 bars", 20, "autocorr"),
        ("fracret_0_35", "Fractional return transform d=0.35, m=50", 50, "fracret"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="physics_regime",
            subfamily="persistence",
            regular_or_physics="physics",
            lookback=lookback,
            formula_group=formula_group,
            depends_on=["close"],
            formula=english,
            economic_thesis="Persistence and regime structure may improve robustness across changing market states.",
            expected_sign="mixed",
            family_cap_weight=0.5,
            interpretability_tag="medium",
        )

    # Volatility-clustering context family.
    for name, english, subfamily in [
        ("vol_pct_rank_34", "Percentile rank of realized_vol_13 over 34 bars", "vol_percentile"),
        ("vol_pct_rank_89", "Percentile rank of realized_vol_13 over 89 bars", "vol_percentile"),
        ("vol_cluster_high_34", "High-vol regime flag (>=80th pct, 34 bars)", "regime_flag"),
        ("vol_cluster_low_34", "Low-vol regime flag (<=20th pct, 34 bars)", "regime_flag"),
        ("consecutive_high_vol_bars", "Consecutive high-vol bars", "run_length"),
        ("consecutive_low_vol_bars", "Consecutive low-vol bars", "run_length"),
        ("regime_duration_high_vol", "High-vol regime duration", "run_length"),
        ("regime_duration_low_vol", "Low-vol regime duration", "run_length"),
    ]:
        _row(
            feature_name=name,
            english_name=english,
            family="volatility_clustering",
            subfamily=subfamily,
            regular_or_physics="regular",
            lookback=None,
            formula_group=subfamily,
            depends_on=["realized_vol_13"],
            formula=english,
            economic_thesis="Volatility-cluster context can identify when continuation or selectivity is more reliable.",
            expected_sign="mixed",
            family_cap_weight=0.5,
            interpretability_tag="context",
        )

    # Cross-sectional z-score features.
    for feature_name, english, base in [
        ("xs_ret_5_z", "Cross-sectional z-score of 5-bar return", "ret_5"),
        ("xs_ret_20_z", "Cross-sectional z-score of 20-bar return", "ret_20"),
        ("xs_rsi_14_z", "Cross-sectional z-score of RSI(14)", "rsi_14"),
        ("xs_atr_pct_14_z", "Cross-sectional z-score of ATR_pct(14)", "atr_pct_14"),
        ("xs_rel_volume_20_z", "Cross-sectional z-score of rel_volume_20", "rel_volume_20"),
    ]:
        _row(
            feature_name=feature_name,
            english_name=english,
            family="cross_sectional",
            subfamily="z_score",
            regular_or_physics="regular",
            lookback=None,
            formula_group="xs_zscore",
            depends_on=[base],
            formula=f"Cross-sectional z-score of {base}",
            economic_thesis="Relative cross-sectional strength or weakness can improve ranking quality at a timestamp.",
            expected_sign="positive",
            family_cap_weight=0.5,
            interpretability_tag="high",
        )

    def _infer_meta(feat: str) -> Tuple[str, str, str, Sequence[str], str]:
        digits = [int(tok) for tok in feat.split("_") if tok.isdigit()]
        lookback = max(digits) if digits else None
        regular_or_physics = "physics" if feat in PHYSICS_FEATURES else "regular"
        family = "returns_momentum"
        subfamily = "misc"
        formula_group = "derived"
        depends: Sequence[str] = ["close"]

        if feat.startswith("xs_"):
            return "cross_sectional", "z_score", regular_or_physics, [], "xs_zscore"
        if feat in VOLATILITY_CLUSTERING_FEATURES:
            return "volatility_clustering", "regime_context", regular_or_physics, ["realized_vol_13"], "volatility_clustering"
        if feat.startswith("ret_") or feat.startswith("roc_") or feat.startswith("cumret_") or feat.startswith("ret_z_"):
            return "returns_momentum", "returns", regular_or_physics, ["close"], "returns"
        if feat.startswith("up_bar_ratio_") or feat.startswith("momentum_") or feat == "logret_1":
            return "returns_momentum", "momentum", regular_or_physics, ["close"], "momentum"
        if feat.startswith("ema_") or feat.startswith("sma_") or feat.startswith("price_vs_") or feat.startswith("trend_"):
            return "trend_ma", "trend_structure", regular_or_physics, ["close"], "trend_ma"
        if feat.startswith("rsi_") or feat.startswith("stoch_") or feat.startswith("williams_") or feat.startswith("cci_"):
            return "oscillator", "oscillator", regular_or_physics, ["high", "low", "close"], "oscillator"
        if feat.startswith("macd_") or feat.startswith("ppo_"):
            return "macd_ppo", "macd_ppo", regular_or_physics, ["close"], "macd_ppo"
        if feat.startswith("atr_") or feat.startswith("tr_") or feat.startswith("range_") or "vol" in feat or feat.startswith("bb_") or feat.startswith("keltner_") or feat.startswith("donchian_") or feat.startswith("breakout_") or feat.startswith("squeeze_"):
            return "volatility_range", "volatility_channels", regular_or_physics, ["high", "low", "close", "open"], "volatility_range"
        if feat.startswith("adx_") or feat.startswith("plus_di_") or feat.startswith("minus_di_"):
            return "trend_strength", "adx_di", regular_or_physics, ["high", "low", "close"], "adx_di"
        if feat.startswith("vol_z_") or feat.startswith("rel_volume_") or feat.startswith("volume_") or feat.startswith("obv") or feat.startswith("cmf_") or feat.startswith("mfi_") or feat.startswith("force_index_") or feat.startswith("vpt_"):
            return "volume_flow", "volume_flow", regular_or_physics, ["high", "low", "close", "volume"], "volume_flow"
        if feat.startswith("session_vwap_") or feat.startswith("rolling_vwap_") or feat.startswith("pivot_") or feat.startswith("dist_to_roll_") or feat.startswith("range_position_") or feat.startswith("body_") or feat.startswith("upper_wick_") or feat.startswith("lower_wick_") or feat.startswith("close_location_") or feat.startswith("gap_open_"):
            return "price_location", "vwap_support_resistance", regular_or_physics, ["open", "high", "low", "close", "volume"], "price_location"
        if regular_or_physics == "physics":
            if feat.startswith("hurst_") or feat.startswith("variance_ratio_"):
                return "physics_regime", "persistence", regular_or_physics, ["close"], "variance_ratio_proxy"
            if feat.startswith("entropy_"):
                return "physics_regime", "entropy", regular_or_physics, ["close"], "entropy"
            if feat.startswith("autocorr_"):
                return "physics_regime", "autocorrelation", regular_or_physics, ["close"], "autocorr"
            if feat.startswith("fracret_"):
                return "physics_regime", "fractional", regular_or_physics, ["close"], "fracret"
            if feat.startswith("fractal_") or feat.startswith("pfe_") or feat.startswith("roughness_"):
                return "physics_regime", "fractal", regular_or_physics, ["high", "low", "close"], "fractal_path"
            if feat.startswith("rolling_skew_") or feat.startswith("rolling_kurt_"):
                return "physics_regime", "distribution_shape", regular_or_physics, ["close"], "distribution_shape"
        _ = lookback  # quiet linters in branches that don't use lookback directly
        return family, subfamily, regular_or_physics, depends, formula_group

    # Mark any features present in the model feature list but missing from explicit rows using inferred metadata.
    implemented_names = {r["feature_name"] for r in rows}
    for feat in features:
        if feat in implemented_names:
            continue
        family, subfamily, regular_or_physics, depends_on, formula_group = _infer_meta(feat)
        digits = [int(tok) for tok in feat.split("_") if tok.isdigit()]
        lookback = max(digits) if digits else None
        _row(
            feature_name=feat,
            english_name=feat.replace("_", " "),
            family=family,
            subfamily=subfamily,
            regular_or_physics=regular_or_physics,
            lookback=lookback,
            formula_group=formula_group,
            depends_on=list(depends_on),
            formula=feat,
            expected_sign="mixed",
            notes="Feature metadata inferred from naming convention.",
        )

    df = pd.DataFrame(rows, columns=list(REGISTRY_FIELDS))
    return df


def add_per_ticker_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy().reset_index(drop=True)
    c = g["close"].astype(float)
    h = g["high"].astype(float)
    l = g["low"].astype(float)
    o = g["open"].astype(float)
    v = g["volume"].astype(float)
    eps = 1e-12
    # 1-bar log returns and simple returns
    ret1 = c.pct_change()
    lr1 = np.log(c / c.shift(1).replace(0, np.nan))
    g["ret_1"] = ret1
    for n in (2, 3, 5, 8, 10, 13, 20, 21, 34, 55):
        g[f"ret_{n}"] = c.pct_change(n)
    g["logret_1"] = lr1
    g["roc_5"] = c.pct_change(5)
    g["roc_10"] = c.pct_change(10)
    g["roc_20"] = c.pct_change(20)
    g["ret_z_13"] = (ret1 - ret1.rolling(13).mean()) / ret1.rolling(13).std().replace(0, np.nan)
    g["ret_z_34"] = (ret1 - ret1.rolling(34).mean()) / ret1.rolling(34).std().replace(0, np.nan)
    # Vectorized rolling product: prod(1+r) = exp(sum(log1p(r)))
    log1p_ret = np.log1p(ret1)
    g["cumret_13"] = np.exp(log1p_ret.rolling(13).sum()) - 1.0
    g["cumret_34"] = np.exp(log1p_ret.rolling(34).sum()) - 1.0
    g["cumret_55"] = np.exp(log1p_ret.rolling(55).sum()) - 1.0
    g["up_bar_ratio_13"] = ret1.gt(0).astype(float).rolling(13).mean()
    g["up_bar_ratio_34"] = ret1.gt(0).astype(float).rolling(34).mean()
    g["momentum_5_over_21"] = g["ret_5"] - g["ret_21"]
    g["momentum_13_over_34"] = g["ret_13"] - g["ret_34"]

    ema5 = c.ewm(span=5, adjust=False).mean()
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema13 = c.ewm(span=13, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema34 = c.ewm(span=34, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema55 = c.ewm(span=55, adjust=False).mean()
    ema89 = c.ewm(span=89, adjust=False).mean()
    g["ema_gap_5_13"] = ema5 / ema13 - 1
    g["ema_gap_10_20"] = ema10 / ema20 - 1
    g["ema_gap_13_34"] = ema13 / ema34 - 1
    g["ema_gap_20_50"] = ema20 / ema50 - 1
    g["ema_gap_34_55"] = ema34 / ema55 - 1
    g["ema_gap_55_89"] = ema55 / ema89 - 1
    sma13 = c.rolling(13).mean()
    sma21 = c.rolling(21).mean()
    sma34 = c.rolling(34).mean()
    sma55 = c.rolling(55).mean()
    g["sma_gap_13_34"] = sma13 / sma34 - 1
    g["sma_gap_34_55"] = sma34 / sma55 - 1
    g["price_vs_ema_13"] = c / ema13 - 1
    g["price_vs_ema20"] = c / ema20 - 1
    g["price_vs_ema_34"] = c / ema34 - 1
    g["price_vs_ema50"] = c / ema50 - 1
    g["price_vs_ema_55"] = c / ema55 - 1
    g["price_vs_sma_21"] = c / sma21 - 1
    g["price_vs_sma_55"] = c / sma55 - 1
    g["ema_slope_13"] = (ema13 - ema13.shift(3)) / ema13.shift(3).replace(0, np.nan)
    g["ema_slope_34"] = (ema34 - ema34.shift(5)) / ema34.shift(5).replace(0, np.nan)
    g["ema_slope_55"] = (ema55 - ema55.shift(8)) / ema55.shift(8).replace(0, np.nan)
    trend_state = (ema13 > ema34).astype(float)
    g["trend_persistence_13"] = trend_state.rolling(13).mean()
    g["trend_persistence_34"] = trend_state.rolling(34).mean()

    delta = c.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up_7 = up.ewm(alpha=1 / 7, adjust=False).mean()
    roll_down_7 = down.ewm(alpha=1 / 7, adjust=False).mean()
    rs_7 = roll_up_7 / roll_down_7.replace(0, np.nan)
    g["rsi_7"] = 100 - (100 / (1 + rs_7))
    roll_up = up.ewm(alpha=1 / 14, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / 14, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    g["rsi_14"] = 100 - (100 / (1 + rs))
    roll_up_21 = up.ewm(alpha=1 / 21, adjust=False).mean()
    roll_down_21 = down.ewm(alpha=1 / 21, adjust=False).mean()
    rs_21 = roll_up_21 / roll_down_21.replace(0, np.nan)
    g["rsi_21"] = 100 - (100 / (1 + rs_21))

    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    k14 = ((c - low14) / (high14 - low14).replace(0, np.nan)) * 100
    g["stoch_k_14_3"] = k14.rolling(3).mean()
    g["stoch_d_14_3"] = g["stoch_k_14_3"].rolling(3).mean()
    low21 = l.rolling(21).min()
    high21 = h.rolling(21).max()
    k21 = ((c - low21) / (high21 - low21).replace(0, np.nan)) * 100
    g["stoch_k_21_3"] = k21.rolling(3).mean()
    g["stoch_d_21_3"] = g["stoch_k_21_3"].rolling(3).mean()
    g["williams_r_14"] = -100.0 * (high14 - c) / (high14 - low14).replace(0, np.nan)
    g["williams_r_21"] = -100.0 * (high21 - c) / (high21 - low21).replace(0, np.nan)
    tp = (h + l + c) / 3
    # Vectorized rolling MAD: mean(|x - mean(x)|)
    dev20 = tp - tp.rolling(20).mean()
    dev34 = tp - tp.rolling(34).mean()
    mad20 = dev20.abs().rolling(20).mean()
    mad34 = dev34.abs().rolling(34).mean()
    g["cci_20"] = (tp - tp.rolling(20).mean()) / (0.015 * mad20.replace(0, np.nan))
    g["cci_34"] = (tp - tp.rolling(34).mean()) / (0.015 * mad34.replace(0, np.nan))

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    g["macd_12_26_9"] = macd
    g["macd_signal_12_26_9"] = signal
    g["macd_hist_12_26_9"] = macd - signal
    macd_13_34 = ema13 - ema34
    signal_13_34 = macd_13_34.ewm(span=8, adjust=False).mean()
    g["macd_13_34_8"] = macd_13_34
    g["macd_signal_13_34_8"] = signal_13_34
    g["macd_hist_13_34_8"] = macd_13_34 - signal_13_34
    g["ppo_12_26"] = 100.0 * (ema12 - ema26) / ema26.replace(0, np.nan)

    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - l).abs(), (h - prev_close).abs(), (l - prev_close).abs()], axis=1
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    g["atr_14"] = atr
    g["atr_pct_14"] = atr / c.replace(0, np.nan)
    atr21 = tr.ewm(alpha=1 / 21, adjust=False).mean()
    atr34 = tr.ewm(alpha=1 / 34, adjust=False).mean()
    g["atr_21"] = atr21
    g["atr_34"] = atr34
    g["atr_pct_21"] = atr21 / c.replace(0, np.nan)
    g["atr_pct_34"] = atr34 / c.replace(0, np.nan)
    g["tr_pct_1"] = tr / c.replace(0, np.nan)

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=g.index)
    minus_dm = pd.Series(minus_dm, index=g.index)

    plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr.replace(0, np.nan))
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    g["plus_di_14"] = plus_di
    g["minus_di_14"] = minus_di
    g["adx_14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di_21 = 100 * (plus_dm.ewm(alpha=1 / 21, adjust=False).mean() / atr21.replace(0, np.nan))
    minus_di_21 = 100 * (minus_dm.ewm(alpha=1 / 21, adjust=False).mean() / atr21.replace(0, np.nan))
    dx21 = ((plus_di_21 - minus_di_21).abs() / (plus_di_21 + minus_di_21).replace(0, np.nan)) * 100
    g["plus_di_21"] = plus_di_21
    g["minus_di_21"] = minus_di_21
    g["adx_21"] = dx21.ewm(alpha=1 / 21, adjust=False).mean()
    g["adx_slope_5"] = (g["adx_14"] - g["adx_14"].shift(5)) / 5.0

    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    g["bb_pos_20_2"] = (c - lower) / (upper - lower).replace(0, np.nan)
    g["bb_width_20_2"] = (upper - lower) / sma20.replace(0, np.nan)
    sma34 = c.rolling(34).mean()
    std34 = c.rolling(34).std()
    upper34 = sma34 + 2 * std34
    lower34 = sma34 - 2 * std34
    g["bb_pos_34_2"] = (c - lower34) / (upper34 - lower34).replace(0, np.nan)
    g["bb_width_34_2"] = (upper34 - lower34) / sma34.replace(0, np.nan)

    keltner_mid = ema20
    keltner_up = keltner_mid + 2.0 * atr21
    keltner_dn = keltner_mid - 2.0 * atr21
    g["keltner_pos_20_2"] = (c - keltner_dn) / (keltner_up - keltner_dn).replace(0, np.nan)
    g["keltner_width_20_2"] = (keltner_up - keltner_dn) / keltner_mid.replace(0, np.nan)

    d_hi = h.rolling(20).max()
    d_lo = l.rolling(20).min()
    g["donchian_pos_20"] = (c - d_lo) / (d_hi - d_lo).replace(0, np.nan)
    d_hi55 = h.rolling(55).max()
    d_lo55 = l.rolling(55).min()
    g["donchian_pos_55"] = (c - d_lo55) / (d_hi55 - d_lo55).replace(0, np.nan)
    g["breakout_up_20"] = (c > h.rolling(20).max().shift(1)).astype(float)
    g["breakout_up_55"] = (c > h.rolling(55).max().shift(1)).astype(float)
    g["breakout_down_20"] = (c < l.rolling(20).min().shift(1)).astype(float)
    g["breakout_down_55"] = (c < l.rolling(55).min().shift(1)).astype(float)
    g["squeeze_on_20"] = (g["bb_width_20_2"] < g["keltner_width_20_2"]).astype(float)

    g["range_pct_1"] = (h - l) / c.replace(0, np.nan)
    g["range_pct_5"] = (h.rolling(5).max() - l.rolling(5).min()) / c.replace(0, np.nan)
    g["range_pct_13"] = (h.rolling(13).max() - l.rolling(13).min()) / c.replace(0, np.nan)
    g["realized_vol_10"] = lr1.rolling(10).std()
    g["realized_vol_20"] = lr1.rolling(20).std()
    g["realized_vol_13"] = lr1.rolling(13).std()
    g["realized_vol_34"] = lr1.rolling(34).std()
    g["realized_vol_89"] = lr1.rolling(89).std()
    g["vol_of_vol_13"] = g["realized_vol_13"].rolling(13).std()
    g["vol_of_vol_20"] = g["realized_vol_13"].rolling(20).std()
    g["vol_of_vol_34"] = g["realized_vol_13"].rolling(34).std()
    log_hl = np.log(h / l.replace(0, np.nan))
    g["parkinson_vol_13"] = np.sqrt((log_hl.pow(2)).rolling(13).mean() / (4.0 * np.log(2.0)))
    g["parkinson_vol_34"] = np.sqrt((log_hl.pow(2)).rolling(34).mean() / (4.0 * np.log(2.0)))
    u = np.log(h / o.replace(0, np.nan))
    d = np.log(l / o.replace(0, np.nan))
    cl = np.log(c / o.replace(0, np.nan))
    gk_var = 0.5 * (u - d).pow(2) - (2 * np.log(2) - 1) * cl.pow(2)
    g["garman_klass_vol_13"] = np.sqrt(gk_var.clip(lower=0).rolling(13).mean())

    vol_mean20 = v.rolling(20).mean()
    vol_std20 = v.rolling(20).std()
    g["vol_z_20"] = (v - vol_mean20) / vol_std20.replace(0, np.nan)
    g["rel_volume_20"] = v / vol_mean20.replace(0, np.nan)
    vol_mean60 = v.rolling(60).mean()
    vol_std60 = v.rolling(60).std()
    g["vol_z_60"] = (v - vol_mean60) / vol_std60.replace(0, np.nan)
    g["rel_volume_60"] = v / vol_mean60.replace(0, np.nan)
    g["volume_ema_gap_10_20"] = (
        v.ewm(span=10, adjust=False).mean()
        / v.ewm(span=20, adjust=False).mean().replace(0, np.nan)
        - 1
    )
    obv = (np.sign(c.diff().fillna(0)) * v).fillna(0).cumsum()
    g["obv"] = obv
    g["obv_slope_5"] = obv.diff(5) / 5
    g["obv_slope_13"] = obv.diff(13) / 13
    mfv = (((c - l) - (h - c)) / (h - l).replace(0, np.nan)) * v
    g["cmf_20"] = mfv.rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    rmf = tp * v
    tp_diff = tp.diff()
    pos_mf = rmf.where(tp_diff > 0, 0.0)
    neg_mf = rmf.where(tp_diff < 0, 0.0).abs()
    mfr = pos_mf.rolling(14).sum() / neg_mf.rolling(14).sum().replace(0, np.nan)
    g["mfi_14"] = 100 - (100 / (1 + mfr))
    force_raw = c.diff() * v
    g["force_index_13"] = force_raw.ewm(span=13, adjust=False).mean()
    vpt = (v * c.pct_change().fillna(0.0)).cumsum()
    g["vpt_slope_13"] = vpt.diff(13) / 13

    # Session-aware VWAP features.
    ts = pd.to_datetime(g["timestamp_utc"], utc=True)
    if "session_date_ny" in g.columns:
        session_key = g["session_date_ny"].astype(str)
    else:
        session_key = ts.dt.tz_convert("America/New_York").dt.date.astype(str)
    cum_pv = (tp * v).groupby(session_key).cumsum()
    cum_v = v.groupby(session_key).cumsum()
    session_vwap = cum_pv / cum_v.replace(0, np.nan)
    g["session_vwap_dist"] = c / session_vwap.replace(0, np.nan) - 1.0
    rolling_vwap_13 = (tp * v).rolling(13).sum() / v.rolling(13).sum().replace(0, np.nan)
    rolling_vwap_34 = (tp * v).rolling(34).sum() / v.rolling(34).sum().replace(0, np.nan)
    g["rolling_vwap_dist_13"] = c / rolling_vwap_13.replace(0, np.nan) - 1.0
    g["rolling_vwap_dist_34"] = c / rolling_vwap_34.replace(0, np.nan) - 1.0
    sess_stats = (
        pd.DataFrame({"session": session_key, "high": h, "low": l, "close": c})
        .groupby("session", sort=True)
        .agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    )
    sess_stats["pivot_prev_day"] = ((sess_stats["high"] + sess_stats["low"] + sess_stats["close"]) / 3.0).shift(1)
    pivot_prev = session_key.map(sess_stats["pivot_prev_day"])
    g["pivot_dist_prev_day"] = (c - pivot_prev) / c.replace(0, np.nan)
    g["dist_to_roll_high_20"] = (c - h.rolling(20).max().shift(1)) / c.replace(0, np.nan)
    g["dist_to_roll_high_55"] = (c - h.rolling(55).max().shift(1)) / c.replace(0, np.nan)
    g["dist_to_roll_low_20"] = (c - l.rolling(20).min().shift(1)) / c.replace(0, np.nan)
    g["dist_to_roll_low_55"] = (c - l.rolling(55).min().shift(1)) / c.replace(0, np.nan)
    g["range_position_20"] = (c - l.rolling(20).min()) / (h.rolling(20).max() - l.rolling(20).min()).replace(0, np.nan)
    g["range_position_55"] = (c - l.rolling(55).min()) / (h.rolling(55).max() - l.rolling(55).min()).replace(0, np.nan)
    g["body_pct_1"] = (c - o).abs() / (h - l).replace(0, np.nan)
    g["upper_wick_pct_1"] = (h - np.maximum(c, o)) / (h - l).replace(0, np.nan)
    g["lower_wick_pct_1"] = (np.minimum(c, o) - l) / (h - l).replace(0, np.nan)
    g["close_location_value_1"] = (2.0 * c - h - l) / (h - l).replace(0, np.nan)
    g["gap_open_pct_1"] = (o - c.shift(1)) / c.shift(1).replace(0, np.nan)

    # Physics / regime block.
    vr_5_34 = variance_ratio(c, lag=5, window=34)
    vr_5_50 = variance_ratio(c, lag=5, window=50)
    vr_5_55 = variance_ratio(c, lag=5, window=55)
    vr_5_89 = variance_ratio(c, lag=5, window=89)
    vr_13_89 = variance_ratio(c, lag=13, window=89)
    g["variance_ratio_5_34"] = vr_5_34
    g["variance_ratio_5_55"] = vr_5_55
    g["variance_ratio_13_89"] = vr_13_89
    g["hurst_proxy_34"] = 0.5 * (1.0 + np.log(vr_5_34) / np.log(5.0))
    g["hurst_proxy_50"] = 0.5 * (1.0 + np.log(vr_5_50) / np.log(5.0))
    g["hurst_proxy_55"] = 0.5 * (1.0 + np.log(vr_5_55) / np.log(5.0))
    g["hurst_proxy_89"] = 0.5 * (1.0 + np.log(vr_5_89) / np.log(5.0))
    pos_frac = ret1.gt(0).astype(float).rolling(20).mean()
    g["entropy_sign_20"] = binary_entropy(pos_frac)
    g["entropy_sign_34"] = binary_entropy(ret1.gt(0).astype(float).rolling(34).mean())
    g["entropy_sign_55"] = binary_entropy(ret1.gt(0).astype(float).rolling(55).mean())

    def _rolling_hist_entropy(series: pd.Series, window: int, bins: int = 10) -> pd.Series:
        def _entropy_last(x: np.ndarray) -> float:
            vals = np.asarray(x, dtype=float)
            vals = vals[np.isfinite(vals)]
            if len(vals) == 0:
                return np.nan
            lo = float(np.min(vals))
            hi = float(np.max(vals))
            if not np.isfinite(lo) or not np.isfinite(hi):
                return np.nan
            if abs(hi - lo) < eps:
                return 0.0
            hist, _ = np.histogram(vals, bins=bins, range=(lo, hi))
            total = hist.sum()
            if total <= 0:
                return np.nan
            p = hist[hist > 0].astype(float) / float(total)
            return float(-(p * np.log(p)).sum() / np.log(float(bins)))

        return series.rolling(window).apply(_entropy_last, raw=True)

    g["entropy_return_hist_20"] = _rolling_hist_entropy(lr1, 20)
    g["entropy_return_hist_34"] = _rolling_hist_entropy(lr1, 34)
    g["autocorr_1_20"] = ret1.rolling(20).corr(ret1.shift(1))
    g["autocorr_5_20"] = ret1.rolling(20).corr(ret1.shift(5))
    g["autocorr_1_34"] = ret1.rolling(34).corr(ret1.shift(1))
    g["autocorr_5_34"] = ret1.rolling(34).corr(ret1.shift(5))
    abs_ret = ret1.abs()
    g["autocorr_absret_1_20"] = abs_ret.rolling(20).corr(abs_ret.shift(1))
    g["autocorr_absret_1_34"] = abs_ret.rolling(34).corr(abs_ret.shift(1))
    g["fracret_0_35"] = fracret(ret1)
    g["fracret_0_50"] = fracret(ret1, weights=frac_weights(0.50, 50))
    for n in (20, 34, 55):
        path_n = tr.rolling(n).sum()
        range_n = h.rolling(n).max() - l.rolling(n).min()
        fd = 1.0 + (
            np.log(path_n.clip(lower=eps))
            - np.log(range_n.clip(lower=eps))
        ) / np.log(float(n))
        rough = path_n / range_n.replace(0, np.nan)
        if n == 20:
            g["fractal_dimension_proxy_20"] = fd
            g["roughness_index_20"] = rough
        elif n == 34:
            g["fractal_dimension_proxy_34"] = fd
            g["roughness_index_34"] = rough
        else:
            g["fractal_dimension_proxy_55"] = fd
    for n in (13, 34):
        disp = c - c.shift(n)
        straight = np.sign(disp) * np.sqrt(disp.pow(2) + float(n * n))
        path = np.sqrt(c.diff().pow(2) + 1.0).rolling(n).sum()
        g[f"pfe_{n}"] = 100.0 * straight / path.replace(0, np.nan)
    g["rolling_skew_34"] = lr1.rolling(34).skew()
    g["rolling_kurt_34"] = lr1.rolling(34).kurt()

    # Volatility-clustering / regime-duration context features.
    vol13 = g["realized_vol_13"]

    def _pct_rank(series: pd.Series, window: int) -> pd.Series:
        def _rank_last(x: np.ndarray) -> float:
            if len(x) == 0 or not np.isfinite(x[-1]):
                return np.nan
            vals = x.astype(float)
            vals = vals[np.isfinite(vals)]
            if len(vals) == 0:
                return np.nan
            last = float(x[-1])
            less = float(np.sum(vals < last))
            equal = float(np.sum(vals == last))
            return (less + 0.5 * equal) / float(len(vals))

        return series.rolling(window).apply(_rank_last, raw=True).astype(float)

    g["vol_pct_rank_34"] = _pct_rank(vol13, 34)
    g["vol_pct_rank_89"] = _pct_rank(vol13, 89)
    g["vol_cluster_high_34"] = (g["vol_pct_rank_34"] >= 0.80).astype(float)
    g["vol_cluster_low_34"] = (g["vol_pct_rank_34"] <= 0.20).astype(float)
    g["vol_persistence_high_13"] = g["vol_cluster_high_34"].rolling(13).mean()
    g["vol_persistence_high_34"] = g["vol_cluster_high_34"].rolling(34).mean()
    g["vol_persistence_low_13"] = g["vol_cluster_low_34"].rolling(13).mean()
    g["vol_persistence_low_34"] = g["vol_cluster_low_34"].rolling(34).mean()

    def _run_length(state: pd.Series) -> pd.Series:
        run = np.zeros(len(state), dtype=float)
        on = state.values.astype(bool)
        for i in range(len(on)):
            if not on[i]:
                run[i] = 0.0
            elif i == 0:
                run[i] = 1.0
            else:
                run[i] = run[i - 1] + 1.0
        return pd.Series(run, index=state.index)

    high_state = g["vol_cluster_high_34"] > 0.5
    low_state = g["vol_cluster_low_34"] > 0.5
    g["consecutive_high_vol_bars"] = _run_length(high_state.astype(float))
    g["consecutive_low_vol_bars"] = _run_length(low_state.astype(float))
    g["regime_duration_high_vol"] = g["consecutive_high_vol_bars"]
    g["regime_duration_low_vol"] = g["consecutive_low_vol_bars"]
    g["vol_regime_change_5"] = g["vol_pct_rank_34"] - g["vol_pct_rank_34"].shift(5)
    g["vol_regime_change_13"] = g["vol_pct_rank_34"] - g["vol_pct_rank_34"].shift(13)
    vol_mean34 = vol13.rolling(34).mean()
    vol_std34 = vol13.rolling(34).std()
    g["vol_spike_flag"] = (vol13 > (vol_mean34 + 2.0 * vol_std34)).astype(float)
    g["vol_cooling_flag"] = (vol13 < (vol_mean34 - 1.0 * vol_std34)).astype(float)
    g["vol_x_momentum_13"] = vol13 * g["ret_13"]
    g["vol_x_trend_strength"] = vol13 * g["adx_14"]
    g["vol_x_breakout_state"] = vol13 * g["breakout_up_20"]
    g["vol_x_rel_volume"] = vol13 * g["rel_volume_20"]

    g["next_open"] = o.shift(-1)
    return g


def build_feature_matrix(
    panel: pd.DataFrame, config: PipelineConfig
) -> Tuple[pd.DataFrame, List[str]]:
    groups = list(panel.groupby("ticker", sort=False))
    pieces = []
    panel_cols = set(panel.columns)
    for i, (ticker, g) in enumerate(groups, start=1):
        logging.info("Feature matrix: ticker %s/%s (%s, %s rows)", i, len(groups), ticker, len(g))
        piece = add_per_ticker_features(g)
        new_cols = [c for c in piece.columns if c not in panel_cols]
        for c in new_cols:
            if pd.api.types.is_numeric_dtype(piece[c]):
                piece[c] = piece[c].astype(np.float32)
        pieces.append(piece)
    df = pd.concat(pieces, ignore_index=True, copy=False).sort_values(["timestamp_utc", "ticker"]).reset_index(drop=True)
    logging.info("Feature matrix: concat done, computing cross-sectional z-scores...")
    # Cross-sectional z-scores on selected features (per explicit addendum).
    xs_cols = [
        ("ret_5", "xs_ret_5_z"),
        ("ret_13", "xs_ret_13_z"),
        ("ret_20", "xs_ret_20_z"),
        ("ret_34", "xs_ret_34_z"),
        ("rsi_14", "xs_rsi_14_z"),
        ("atr_pct_14", "xs_atr_pct_14_z"),
        ("rel_volume_20", "xs_rel_volume_20_z"),
    ]
    for base_name, xs_name in xs_cols:
        mean = df.groupby("timestamp_utc")[base_name].transform("mean")
        std = df.groupby("timestamp_utc")[base_name].transform("std")
        std = std.where(std.abs() >= 1e-12, 1.0)  # per addendum: fall back to 0 z when std ~ 0
        df[xs_name] = (df[base_name] - mean) / std
        df[xs_name] = df[xs_name].fillna(0.0)

    features = list(
        dict.fromkeys(
            CORE_FEATURES
            + (PHYSICS_FEATURES if config.include_physics_block else [])
            + VOLATILITY_CLUSTERING_FEATURES
            + XS_FEATURES
        )
    )
    # Ensure all requested feature columns exist; if a column is missing, create it as NaN so downstream
    # missing-feature gating and the registry can surface the gap explicitly.
    for feat in features:
        if feat not in df.columns:
            df[feat] = np.nan
        df[feat] = df[feat].astype(np.float32)
    return df, features


# ============================================================
# LABELS / EVENT WINDOWS
# ============================================================
def label_long_events(df: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    labeled = []
    for _, g in df.groupby("ticker", sort=False):
        g = g.copy().reset_index(drop=True)
        n = len(g)
        o = g["open"].values.astype(float)
        h = g["high"].values.astype(float)
        l = g["low"].values.astype(float)
        c = g["close"].values.astype(float)
        atr = g["atr_14"].values.astype(float)
        ts = pd.to_datetime(g["timestamp_utc"]).values
        long_win = np.full(n, np.nan)
        event_end_idx = np.full(n, np.nan)
        event_end_time = np.array([np.datetime64("NaT")] * n, dtype="datetime64[ns]")
        entry_open = np.full(n, np.nan)
        stop_price = np.full(n, np.nan)
        target_price = np.full(n, np.nan)
        forward_label_return_net = np.full(n, np.nan)
        for i in range(n):
            if bool(g.at[i, "is_incomplete_session"]):
                continue
            if i + 1 >= n or i + config.max_horizon_bars >= n:
                continue
            entry = o[i + 1]
            entry_open[i] = entry
            if not np.isfinite(entry) or not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            stop = entry - config.stop_atr_multiple * atr[i]
            target = entry + config.target_atr_multiple * atr[i]
            stop_price[i] = stop
            target_price[i] = target
            outcome = 0
            end_idx = i + config.max_horizon_bars
            exit_price = c[end_idx] if np.isfinite(c[end_idx]) else np.nan
            for j in range(i + 1, min(n, i + config.max_horizon_bars + 1)):
                hit_stop = l[j] <= stop
                hit_target = h[j] >= target
                if hit_stop and hit_target:
                    outcome = 0
                    end_idx = j
                    exit_price = stop
                    break
                if hit_stop:
                    outcome = 0
                    end_idx = j
                    exit_price = stop
                    break
                if hit_target:
                    outcome = 1
                    end_idx = j
                    exit_price = target
                    break
            long_win[i] = outcome
            event_end_idx[i] = end_idx
            event_end_time[i] = ts[int(end_idx)]
            entry_exec = entry * (1.0 + config.slippage_per_fill)
            exit_exec = exit_price * (1.0 - config.slippage_per_fill) if np.isfinite(exit_price) else np.nan
            overnights = max(0, int(end_idx) - int(i + 1))
            if np.isfinite(entry_exec) and entry_exec > 0 and np.isfinite(exit_exec):
                forward_label_return_net[i] = (exit_exec / entry_exec) - 1.0 - (config.overnight_brokerage * overnights)
        g["long_win"] = long_win
        g["event_end_idx"] = event_end_idx
        g["event_end_time"] = pd.to_datetime(event_end_time, utc=True)
        g["entry_open_next"] = entry_open
        g["stop_price"] = stop_price
        g["target_price"] = target_price
        g["forward_label_return_net"] = forward_label_return_net
        labeled.append(g)
    out = pd.concat(labeled, ignore_index=True)
    out = out.dropna(subset=["long_win"])
    return out


# ============================================================
# WALK-FORWARD / PURGING
# ============================================================
def build_outer_folds(
    df: pd.DataFrame, config: PipelineConfig
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Build outer time folds. Outer scheme is expanding: train window grows each fold;
    outer_train_months is the initial span."""
    times = sorted(df["timestamp_utc"].drop_duplicates().tolist())
    start = pd.Timestamp(times[0])
    end = pd.Timestamp(times[-1])
    folds = []
    train_end = start + pd.DateOffset(months=config.outer_train_months)
    while train_end < end:
        test_start = train_end
        test_end = min(
            train_end + pd.DateOffset(months=config.outer_test_months),
            end + pd.Timedelta(days=1),
        )
        folds.append((start, train_end, test_start, test_end))
        if test_end >= end:
            break
        train_end = train_end + pd.DateOffset(months=config.outer_test_months)
    return folds


def purged_splits(
    train_df: pd.DataFrame, config: PipelineConfig
) -> List[Tuple[np.ndarray, np.ndarray, Tuple[pd.Timestamp, pd.Timestamp]]]:
    unique_times = np.array(sorted(train_df["timestamp_utc"].drop_duplicates().tolist()))
    blocks = np.array_split(np.arange(len(unique_times)), config.inner_folds)
    splits = []
    for block in blocks:
        val_times = unique_times[block]
        val_start = pd.Timestamp(val_times[0])
        val_end = pd.Timestamp(val_times[-1])
        end_pos = block[-1]
        embargo_end_pos = min(len(unique_times) - 1, end_pos + config.embargo_bars)
        embargo_end = pd.Timestamp(unique_times[embargo_end_pos])
        is_val = train_df["timestamp_utc"].between(val_start, val_end)
        overlap = (train_df["timestamp_utc"] <= val_end) & (
            train_df["event_end_time"] >= val_start
        )
        embargo = (train_df["timestamp_utc"] > val_end) & (
            train_df["timestamp_utc"] <= embargo_end
        )
        train_mask = (~is_val) & (~overlap) & (~embargo)
        splits.append((train_mask.values, is_val.values, (val_start, val_end)))
    return splits


def purge_outer_train_boundary(
    train_df: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    """Remove rows whose event_end_time extends into the test window (outer-boundary leakage).
    Rows with event_end_time NaT are excluded (cannot verify they end before cutoff)."""
    valid = train_df["event_end_time"].notna() & (train_df["event_end_time"] < cutoff)
    return train_df.loc[valid].copy()


# ============================================================
# MODELS / STACKING / CALIBRATION
# ============================================================
def make_models(
    config: PipelineConfig,
    pos_weight: float,
    rf_params: Optional[Dict[str, object]] = None,
    et_params: Optional[Dict[str, object]] = None,
    xgb_params: Optional[Dict[str, object]] = None,
    lgbm_params: Optional[Dict[str, object]] = None,
    enet_params: Optional[Dict[str, object]] = None,
) -> Dict[str, _ClassifierLike]:
    if not LIGHTGBM_AVAILABLE:
        raise RuntimeError(
            "LightGBM is required by the hardened model stack but is not installed. "
            "Install dependencies from requirements.txt."
        )
    _rf = {
        "n_estimators": config.rf_n_estimators,
        "max_depth": config.rf_max_depth,
        "min_samples_leaf": config.rf_min_samples_leaf,
        "max_features": "sqrt",
        "class_weight": "balanced_subsample",
        "bootstrap": True,
        "n_jobs": config.n_jobs_tree_models,
        "random_state": config.random_seed,
    }
    if rf_params:
        _rf.update(rf_params)
    rf = RandomForestClassifier(**_rf)
    _et = {
        "n_estimators": config.et_n_estimators,
        "max_depth": config.et_max_depth,
        "min_samples_leaf": config.et_min_samples_leaf,
        "max_features": "sqrt",
        "class_weight": "balanced_subsample",
        "bootstrap": False,
        "n_jobs": config.n_jobs_tree_models,
        "random_state": config.random_seed + 1,
    }
    if et_params:
        _et.update(et_params)
    et = ExtraTreesClassifier(**_et)
    _xgb = {
        "objective": "binary:logistic",
        "n_estimators": config.xgb_n_estimators,
        "learning_rate": config.xgb_learning_rate,
        "max_depth": config.xgb_max_depth,
        "min_child_weight": config.xgb_min_child_weight,
        "subsample": config.xgb_subsample,
        "colsample_bytree": config.xgb_colsample_bytree,
        "reg_alpha": config.xgb_reg_alpha,
        "reg_lambda": config.xgb_reg_lambda,
        "eval_metric": "logloss",
        "tree_method": "hist",
        "n_jobs": config.n_jobs_xgb,
        "random_state": config.random_seed + 2,
        "scale_pos_weight": pos_weight,
        "verbosity": 0,
    }
    if xgb_params:
        _xgb.update(xgb_params)
    xgb = XGBClassifier(**_xgb)
    _lgbm = {
        "objective": "binary",
        "n_estimators": config.lgbm_n_estimators,
        "learning_rate": config.lgbm_learning_rate,
        "num_leaves": config.lgbm_num_leaves,
        "subsample": config.lgbm_subsample,
        "colsample_bytree": config.lgbm_colsample_bytree,
        "random_state": config.random_seed + 3,
        "n_jobs": config.n_jobs_tree_models,
        "class_weight": "balanced",
        "verbosity": -1,
    }
    if lgbm_params:
        _lgbm.update(lgbm_params)
    lgbm = LGBMClassifier(**_lgbm)
    _enet = {
        "penalty": "elasticnet",
        "C": config.enet_c,
        "l1_ratio": config.enet_l1_ratio,
        "solver": "saga",
        "max_iter": 2000,
        "class_weight": "balanced",
        "random_state": config.random_seed + 4,
    }
    if enet_params:
        _enet.update(enet_params)
    enet = LogisticRegression(**_enet)
    return {"RF": rf, "ET": et, "XGB": xgb, "LGBM": lgbm, "ENET": enet}


def extract_feature_importance(model: _ClassifierLike, features: Sequence[str]) -> Optional[np.ndarray]:
    if hasattr(model, "feature_importances_"):
        imp = np.asarray(cast(Any, model.feature_importances_), dtype=float)
        return imp if len(imp) == len(features) else None
    if hasattr(model, "coef_"):
        coef = np.asarray(cast(Any, model.coef_), dtype=float)
        if coef.ndim == 2:
            coef = coef[0]
        coef = np.abs(coef)
        return coef if len(coef) == len(features) else None
    return None


def run_optuna_inner(
    train_df: pd.DataFrame,
    config: PipelineConfig,
    features: Sequence[str],
) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Dict[str, Any]]]:
    """Run Optuna over inner CV for RF, ET, XGB with a Phase 1 wall-clock cap per model."""
    if not OPTUNA_AVAILABLE:
        logging.warning("Optuna not available. Using default parameters.")
        return {}, {}

    inner_splits = purged_splits(train_df, config)
    y_train_full = train_df["long_win"].astype(int).values
    pos_weight = max((y_train_full == 0).sum() / max((y_train_full == 1).sum(), 1), 1.0)

    def mean_inner_logloss(model_factory) -> float:
        scores: List[float] = []
        for train_mask, val_mask, _ in inner_splits:
            tr = train_df.loc[train_mask]
            val = train_df.loc[val_mask]
            X_tr_raw = tr[list(features)]
            X_val_raw = val[list(features)]
            y_tr = tr["long_win"].astype(int).values
            y_val = val["long_win"].astype(int).values
            if len(np.unique(y_tr)) < 2 or len(np.unique(y_val)) < 2:
                continue
            X_tr, X_val, _ = impute_fit_transform(X_tr_raw, X_val_raw)
            model = model_factory()
            model.fit(X_tr, y_tr)
            p_val = model.predict_proba(X_val)[:, 1]
            scores.append(log_loss(y_val, clip_prob(p_val), labels=[0, 1]))
        return float(np.mean(scores)) if scores else 1e6

    def objective_rf(trial: _TrialLike) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 150, 450, step=50),
            "max_depth": trial.suggest_int("max_depth", 4, 10),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 50, 200, step=25),
        }
        return mean_inner_logloss(
            lambda: RandomForestClassifier(
                **params,
                max_features="sqrt",
                class_weight="balanced_subsample",
                bootstrap=True,
                n_jobs=config.n_jobs_tree_models,
                random_state=config.random_seed,
            )
        )

    def objective_et(trial: _TrialLike) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 150, 500, step=50),
            "max_depth": trial.suggest_int("max_depth", 4, 10),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 50, 200, step=25),
        }
        return mean_inner_logloss(
            lambda: ExtraTreesClassifier(
                **params,
                max_features="sqrt",
                class_weight="balanced_subsample",
                bootstrap=False,
                n_jobs=config.n_jobs_tree_models,
                random_state=config.random_seed + 1,
            )
        )

    def objective_xgb(trial: _TrialLike) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 150, 450, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 6),
            "min_child_weight": trial.suggest_int("min_child_weight", 20, 80, step=10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 0.9),
        }
        return mean_inner_logloss(
            lambda: XGBClassifier(
                **params,
                objective="binary:logistic",
                eval_metric="logloss",
                tree_method="hist",
                n_jobs=config.n_jobs_xgb,
                random_state=config.random_seed + 2,
                scale_pos_weight=pos_weight,
                reg_alpha=config.xgb_reg_alpha,
                reg_lambda=config.xgb_reg_lambda,
                verbosity=0,
            )
        )

    best_params: Dict[str, Dict[str, object]] = {}
    optuna_summary: Dict[str, Dict[str, Any]] = {}
    sampler = optuna.samplers.TPESampler(seed=config.random_seed)

    def _best_params_or_empty(study: Any) -> Dict[str, object]:
        try:
            params = getattr(study, "best_params", {})
        except Exception:
            return {}
        return {str(key): value for key, value in dict(params).items()}

    def _optimize_model(model_name: str, objective: Callable[[_TrialLike], float]) -> None:
        logging.info(
            "  Optuna %s (n_trials=%s, wall_clock_cap_seconds=%s)...",
            model_name,
            config.optuna_n_trials,
            OPTUNA_MAX_WALL_CLOCK_SECONDS,
        )
        study = optuna.create_study(direction="minimize", sampler=sampler)
        started_at = time.monotonic()
        deadline = started_at + OPTUNA_MAX_WALL_CLOCK_SECONDS
        stopped_for_wall_clock = False

        def _stop_on_wall_clock(study_obj: Any, _trial: Any) -> None:
            nonlocal stopped_for_wall_clock
            if time.monotonic() >= deadline:
                stopped_for_wall_clock = True
                study_obj.stop()

        study.optimize(
            objective,
            n_trials=config.optuna_n_trials,
            show_progress_bar=False,
            callbacks=[_stop_on_wall_clock],
        )
        elapsed_seconds = float(time.monotonic() - started_at)
        params = _best_params_or_empty(study)
        if not params:
            logging.warning(
                "  Optuna %s finished without completed trial parameters inside the %s-second wall-clock cap; using defaults.",
                model_name,
                OPTUNA_MAX_WALL_CLOCK_SECONDS,
            )
        best_params[model_name] = params
        optuna_summary[model_name] = {
            "elapsed_seconds": elapsed_seconds,
            "wall_clock_cap_seconds": int(OPTUNA_MAX_WALL_CLOCK_SECONDS),
            "requested_trials": int(config.optuna_n_trials),
            "completed_trials": int(len(getattr(study, "trials", []))),
            "stopped_for_wall_clock": bool(stopped_for_wall_clock),
        }

    _optimize_model("RF", objective_rf)
    _optimize_model("ET", objective_et)
    _optimize_model("XGB", objective_xgb)
    logging.info("Optuna best params | %s", best_params)
    return best_params, optuna_summary


def impute_fit_transform(
    X_train: pd.DataFrame, X_pred: pd.DataFrame
) -> Tuple[np.ndarray, np.ndarray, SimpleImputer]:
    imp = SimpleImputer(strategy="median")
    return imp.fit_transform(X_train), imp.transform(X_pred), imp


def _fit_calibrated_stack(
    fit_df: pd.DataFrame,
    features: Sequence[str],
    config: PipelineConfig,
    fold_name: str,
    *,
    use_optuna: bool = False,
    log_inner_folds: bool = False,
) -> Tuple[
    LogisticRegression,
    LogisticRegression,
    SimpleImputer,
    pd.DataFrame,
    pd.DataFrame,
    pd.Index,
    pd.DataFrame,
    np.ndarray,
    Dict[str, _ClassifierLike],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    List[Dict[str, object]],
    List[Dict[str, Any]],
    Dict[str, Any],
    Dict[str, Dict[str, Any]],
]:
    """Shared calibration split, OOF base, meta fit, full models, calibrator fit.
    Returns (meta, calibrator, imp, meta_fit_df, calibration_holdout_df, valid_idx,
    oof_base, oof_meta_raw, full_models, X_meta_fit_full, X_calib_full, y_meta_fit_full,
    inner_feature_importance, full_feature_importance, calib_stats)."""
    max_fit_ts = fit_df["timestamp_utc"].max()
    calibration_holdout_start = max_fit_ts - pd.DateOffset(months=config.calibration_holdout_months)
    logging.info("[%s] calibration_holdout_start=%s (for chronology)", fold_name, calibration_holdout_start)
    if calibration_holdout_start <= fit_df["timestamp_utc"].min():
        raise RuntimeError(
            "calibration holdout degenerate (calibration_holdout_start <= purged fit min) | "
            f"calibration_holdout_start={calibration_holdout_start}"
        )
    calibration_holdout_df = fit_df[fit_df["timestamp_utc"] >= calibration_holdout_start].copy()
    meta_fit_df = fit_df[fit_df["timestamp_utc"] < calibration_holdout_start].copy()
    meta_fit_rows_before = len(meta_fit_df)
    meta_fit_df = purge_outer_train_boundary(meta_fit_df, calibration_holdout_start)
    meta_fit_rows_after = len(meta_fit_df)
    logging.info(
        "[%s] Calibration split: meta_fit rows before purge=%s, after purge=%s; calibration_holdout rows=%s",
        fold_name, meta_fit_rows_before, meta_fit_rows_after, len(calibration_holdout_df),
    )
    assert (meta_fit_df["event_end_time"] < calibration_holdout_start).all() if len(meta_fit_df) else True
    ok, reason, calib_stats = calibration_holdout_is_viable(calibration_holdout_df)
    if not ok:
        raise RuntimeError(reason)
    if len(meta_fit_df) == 0:
        raise RuntimeError("meta_fit_df empty after purge; cannot train meta/calibrator")
    if len(meta_fit_df["long_win"].unique()) < 2:
        raise RuntimeError("meta_fit_df lacks both classes; cannot train stack")
    if meta_fit_df["timestamp_utc"].nunique() < config.inner_folds:
        raise RuntimeError(
            f"meta_fit_df has {meta_fit_df['timestamp_utc'].nunique()} unique timestamps "
            f"(need >= inner_folds={config.inner_folds})"
        )

    inner_splits = purged_splits(meta_fit_df, config)
    best_params: Dict[str, Dict[str, object]] = {}
    optuna_summary: Dict[str, Dict[str, Any]] = {}
    if use_optuna and OPTUNA_AVAILABLE:
        best_params, optuna_summary = run_optuna_inner(meta_fit_df, config, features)
    best_rf = best_params.get("RF", {})
    best_et = best_params.get("ET", {})
    best_xgb = best_params.get("XGB", {})
    best_lgbm = best_params.get("LGBM", {})
    best_enet = best_params.get("ENET", {})
    oof_base = pd.DataFrame(index=meta_fit_df.index, columns=list(BASE_MODEL_ORDER), dtype=float)
    inner_feature_importance: List[Dict[str, object]] = []
    for fold_i, (train_mask, val_mask, span) in enumerate(inner_splits, start=1):
        tr = meta_fit_df.loc[train_mask]
        val = meta_fit_df.loc[val_mask]
        X_tr_raw = tr[list(features)]
        X_val_raw = val[list(features)]
        y_tr = tr["long_win"].astype(int).values
        pos_weight = max((y_tr == 0).sum() / max((y_tr == 1).sum(), 1), 1.0)
        X_tr, X_val, _ = impute_fit_transform(X_tr_raw, X_val_raw)
        models = make_models(
            config,
            pos_weight,
            rf_params=best_rf,
            et_params=best_et,
            xgb_params=best_xgb,
            lgbm_params=best_lgbm,
            enet_params=best_enet,
        )
        if log_inner_folds:
            logging.info(
                "Inner fold %s | train=%s | val=%s | span=%s -> %s",
                fold_i, len(tr), len(val), span[0], span[1],
            )
        for name, model in models.items():
            model.fit(X_tr, y_tr)
            oof_base.loc[val.index, name] = model.predict_proba(X_val)[:, 1]
            feat_imp = extract_feature_importance(model, features)
            if feat_imp is not None:
                for feat, imp in zip(features, feat_imp):
                    inner_feature_importance.append(
                        {"fold": fold_i, "model": name, "feature": feat, "importance": float(imp)}
                    )
    valid_idx = oof_base.dropna().index
    meta_input = oof_base.loc[valid_idx].values
    y_meta = meta_fit_df.loc[valid_idx, "long_win"].astype(int).values
    if len(valid_idx) == 0:
        raise RuntimeError("No valid OOF rows available for meta-model training.")
    if len(np.unique(y_meta)) < 2:
        raise RuntimeError("meta_fit_df has only one class after OOF; cannot train meta/calibrator. Skip fold.")
    meta = LogisticRegression(
        penalty="l2",
        C=config.meta_c,
        solver="lbfgs",
        max_iter=1000,
        random_state=config.random_seed + 3,
    )
    meta.fit(meta_input, y_meta)
    oof_meta_raw = meta.predict_proba(meta_input)[:, 1]
    calibrator = LogisticRegression(
        penalty="l2",
        C=config.calibrator_c,
        solver="lbfgs",
        max_iter=1000,
        random_state=config.random_seed + 4,
    )
    X_meta_fit_raw = meta_fit_df[list(features)]
    X_calib_raw = calibration_holdout_df[list(features)]
    y_meta_fit_full = meta_fit_df["long_win"].astype(int).values
    pos_weight = max((y_meta_fit_full == 0).sum() / max((y_meta_fit_full == 1).sum(), 1), 1.0)
    X_meta_fit_full, X_calib_full, imp = impute_fit_transform(X_meta_fit_raw, X_calib_raw)
    full_models = make_models(
        config,
        pos_weight,
        rf_params=best_rf,
        et_params=best_et,
        xgb_params=best_xgb,
        lgbm_params=best_lgbm,
        enet_params=best_enet,
    )
    full_feature_importance: List[Dict[str, Any]] = []
    calib_base: Dict[str, np.ndarray] = {}
    for name, model in full_models.items():
        model.fit(X_meta_fit_full, y_meta_fit_full)
        calib_base[name] = model.predict_proba(X_calib_full)[:, 1]
        feat_imp = extract_feature_importance(model, features)
        if feat_imp is not None:
            for feat, imp_val in zip(features, feat_imp):
                full_feature_importance.append(
                    {"model": name, "feature": feat, "importance": float(imp_val)}
                )
    raw_calib_meta = meta.predict_proba(
        np.column_stack([calib_base[m] for m in BASE_MODEL_ORDER])
    )[:, 1]
    y_calib = calibration_holdout_df["long_win"].astype(int).values
    if len(np.unique(y_calib)) < 2:
        raise RuntimeError("calibration_holdout_df lacks both classes; cannot fit calibrator")
    calibrator.fit(logit(raw_calib_meta).reshape(-1, 1), y_calib)
    return (
        meta,
        calibrator,
        imp,
        meta_fit_df,
        calibration_holdout_df,
        valid_idx,
        oof_base,
        oof_meta_raw,
        full_models,
        X_meta_fit_full,
        X_calib_full,
        y_meta_fit_full,
        inner_feature_importance,
        full_feature_importance,
        calib_stats,
        optuna_summary,
    )


def fit_and_score_prediction_frame(
    fit_df: pd.DataFrame,
    pred_df: pd.DataFrame,
    features: Sequence[str],
    config: PipelineConfig,
    fold_name: str,
    *,
    previous_bucket_positive_rates: Optional[Sequence[float]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Train on fit_df (OOF base within meta_fit_df, meta on OOF base, calibrator on calibration holdout),
    score pred_df out-of-sample.
    Returns (fit_scored, pred_scored, inner_importance_df, full_importance_df, empirical_meta). pred_scored has p_cal and cost_est_r
    and preserves all columns required by choose_thresholds/simulate_book. No fallback for degenerate
    fit_df (single class): caller must skip the fold."""
    (
        meta,
        calibrator,
        imp,
        meta_fit_df,
        _calibration_holdout_df,
        valid_idx,
        _oof_base,
        oof_meta_raw,
        full_models,
        _X_meta_fit_full,
        _X_calib_full,
        _y_meta_fit_full,
        inner_feature_importance,
        full_feature_importance,
        _calib_stats,
        optuna_summary,
    ) = _fit_calibrated_stack(
        fit_df, features, config, fold_name,
        use_optuna=config.use_optuna_tuning and OPTUNA_AVAILABLE,
    )
    fit_meta_cal = calibrator.predict_proba(logit(oof_meta_raw).reshape(-1, 1))[:, 1]
    fit_scored = meta_fit_df.loc[valid_idx].copy()
    fit_scored["p_cal"] = fit_meta_cal
    fit_scored["cost_est_r"] = estimate_cost_r_from_frame(fit_scored, config)
    X_pred_full = imp.transform(pred_df[list(features)])
    pred_base = {name: model.predict_proba(X_pred_full)[:, 1] for name, model in full_models.items()}
    raw_pred_meta = meta.predict_proba(
        np.column_stack([pred_base[m] for m in BASE_MODEL_ORDER])
    )[:, 1]
    pred_cal = calibrator.predict_proba(logit(raw_pred_meta).reshape(-1, 1))[:, 1]
    pred_scored = pred_df.copy()
    pred_scored["p_cal"] = pred_cal
    pred_scored["cost_est_r"] = estimate_cost_r_from_frame(pred_scored, config)
    fit_scored, pred_scored, empirical_meta = apply_empirical_probability_map(
        fit_scored,
        pred_scored,
        config,
        previous_bucket_positive_rates=previous_bucket_positive_rates,
    )
    empirical_meta["optuna_summary"] = optuna_summary
    return (
        fit_scored,
        pred_scored,
        pd.DataFrame(inner_feature_importance),
        pd.DataFrame(full_feature_importance),
        empirical_meta,
    )


def fit_outer_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    features: Sequence[str],
    config: PipelineConfig,
    fold_name: str,
    *,
    previous_bucket_positive_rates: Optional[Sequence[float]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any], Dict[str, Any]]:
    # Calibration holdout inside outer-train (chronology-safe calibration relative to meta-model)
    if config.use_optuna_tuning and not OPTUNA_AVAILABLE:
        logging.warning("Optuna not installed. Skipping tuning.")
    (
        meta,
        calibrator,
        imp,
        meta_fit_df,
        _calibration_holdout_df,
        valid_idx,
        _oof_base,
        oof_meta_raw,
        full_models,
        _X_meta_fit_full,
        _X_calib_full,
        _y_meta_fit_full,
        inner_feature_importance,
        full_feature_importance,
        calib_stats,
        optuna_summary,
    ) = _fit_calibrated_stack(
        train_df, features, config, fold_name,
        use_optuna=config.use_optuna_tuning and OPTUNA_AVAILABLE,
        log_inner_folds=True,
    )
    oof_meta_cal = calibrator.predict_proba(logit(oof_meta_raw).reshape(-1, 1))[:, 1]
    train_scored = meta_fit_df.loc[valid_idx].copy()
    train_scored["p_cal"] = oof_meta_cal
    train_scored["cost_est_r"] = estimate_cost_r_from_frame(train_scored, config)
    X_test_full = imp.transform(test_df[list(features)])
    test_base = {name: model.predict_proba(X_test_full)[:, 1] for name, model in full_models.items()}
    logging.info("Scoring test | meta_fit=%s | test=%s", len(meta_fit_df), len(test_df))
    raw_test_meta = meta.predict_proba(
        np.column_stack([test_base[m] for m in BASE_MODEL_ORDER])
    )[:, 1]
    test_cal = calibrator.predict_proba(logit(raw_test_meta).reshape(-1, 1))[:, 1]
    test_scored = test_df.copy()
    test_scored["p_cal"] = test_cal
    test_scored["cost_est_r"] = estimate_cost_r_from_frame(test_scored, config)
    train_scored, test_scored, empirical_meta = apply_empirical_probability_map(
        train_scored,
        test_scored,
        config,
        previous_bucket_positive_rates=previous_bucket_positive_rates,
    )
    calib_stats = dict(calib_stats)
    calib_stats["optuna_summary"] = optuna_summary
    return (
        train_scored,
        test_scored,
        pd.DataFrame(inner_feature_importance),
        pd.DataFrame(full_feature_importance),
        calib_stats,
        empirical_meta,
    )


# ============================================================
# PORTFOLIO SIMULATION
# ============================================================
@dataclass
class Position:
    ticker: str
    entry_signal_time: pd.Timestamp
    entry_execution_time: pd.Timestamp
    entry_exec_price: float
    entry_reference_price: float
    stop_price: float
    target_price: float
    shares: int
    entry_session_code: int
    p_entry: float
    p_empirical_entry: float
    ev_entry_r: float
    estimated_cost_r: float
    entry_row_idx: int
    entry_regime_label: str
    requested_shares: int
    requested_notional: float
    signal_dollar_volume: float
    signal_adv_dollar_20: float
    projected_participation: float
    capacity_clipped: int


def make_session_codes(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, g in df.groupby("ticker", sort=False):
        g = g.copy().reset_index(drop=True)
        if "session_date_ny" not in g.columns:
            g["session_date_ny"] = pd.to_datetime(g["timestamp_utc"]).dt.tz_convert("America/New_York").dt.date
        unique_sessions = pd.Series(g["session_date_ny"].astype(str)).drop_duplicates().tolist()
        mapping = {d: i for i, d in enumerate(unique_sessions)}
        g["session_code"] = pd.Series(g["session_date_ny"].astype(str)).map(mapping).astype(int)
        g["ticker_row_idx"] = np.arange(len(g))
        g["next_timestamp_utc"] = g["timestamp_utc"].shift(-1)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def compute_metrics(
    trades_df: pd.DataFrame, equity_df: pd.DataFrame, config: PipelineConfig
) -> Dict[str, float]:
    """Portfolio metrics. bars_per_year in config must match actual panel bar frequency (e.g. 252*6.5 for hourly US equity bars)."""
    if len(equity_df) == 0:
        return {
            "n_trades": 0,
            "total_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "calmar": 0.0,
            "daily_cagr": 0.0,
            "daily_mdd": 0.0,
            "daily_calmar": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "avg_hold_hours": 0.0,
            "median_hold_hours": 0.0,
            "ending_equity": 0.0,
            "sharpe": 0.0,
            "sharpe_daily_raw": 0.0,
            "adjusted_sharpe_daily": 0.0,
            "adjusted_sharpe_lag": 0,
            "n_daily_observations": 0,
            "n_nonzero_return_days": 0,
            "notional_turnover_over_avg_equity": 0.0,
            "trades_per_day": 0.0,
            "avg_active_positions": 0.0,
            "median_active_positions": 0.0,
            "p95_active_positions": 0.0,
            "flat_time_fraction": 1.0,
            "at_cap_time_fraction": 0.0,
            "avg_active_exposure": 0.0,
            "avg_participation_rate": 0.0,
            "p95_participation_rate": 0.0,
        }
    eq = equity_df["equity"].astype(float)
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    mdd = abs(float(drawdown.min())) if len(drawdown) else 0.0
    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if eq.iloc[0] != 0 else 0.0
    cagr = annualized_cagr(
        float(eq.iloc[0]), float(eq.iloc[-1]),
        equity_df["timestamp_utc"].iloc[0], equity_df["timestamp_utc"].iloc[-1],
    )
    calmar = cagr / mdd if mdd > 0 else 0.0
    period_returns = eq.pct_change().dropna()
    if len(period_returns) > 1 and period_returns.std() > 0:
        sharpe = float(period_returns.mean() / period_returns.std() * np.sqrt(config.bars_per_year))
    else:
        sharpe = 0.0
    session_dates = session_dates_from_frame(equity_df)
    daily_frame = build_daily_equity_frame(
        equity_df,
        session_dates,
        float(eq.iloc[0]),
        int(max(config.max_concurrent_options) if config.max_concurrent_options else 1),
    )
    daily_eq = daily_frame["equity"].astype(float) if len(daily_frame) else pd.Series(dtype=float)
    if len(daily_eq):
        daily_running_max = daily_eq.cummax()
        daily_drawdown = daily_eq / daily_running_max - 1.0
        daily_mdd = abs(float(daily_drawdown.min())) if len(daily_drawdown) else 0.0
        daily_cagr = annualized_cagr(
            float(daily_eq.iloc[0]),
            float(daily_eq.iloc[-1]),
            pd.Timestamp(str(daily_frame["session_date_ny"].iloc[0])),
            pd.Timestamp(str(daily_frame["session_date_ny"].iloc[-1])),
        )
        daily_calmar = float(daily_cagr / daily_mdd) if daily_mdd > 0 else 0.0
        daily_diag = compute_daily_return_diagnostics(daily_frame["daily_return"].tolist())
        sortino_daily = compute_sortino_ratio(daily_frame["daily_return"].tolist())
    else:
        daily_mdd = 0.0
        daily_cagr = 0.0
        daily_calmar = 0.0
        daily_diag = compute_daily_return_diagnostics([])
        sortino_daily = 0.0

    active_series = (
        equity_df["active_positions"].astype(float)
        if "active_positions" in equity_df.columns
        else pd.Series([0.0] * len(equity_df), index=equity_df.index, dtype=float)
    )
    cap = float(max(config.max_concurrent_options) if config.max_concurrent_options else 1)
    avg_active_positions = float(active_series.mean()) if len(active_series) else 0.0
    median_active_positions = float(active_series.median()) if len(active_series) else 0.0
    p95_active_positions = float(np.quantile(active_series, 0.95)) if len(active_series) else 0.0
    flat_time_fraction = float((active_series <= 0).mean()) if len(active_series) else 1.0
    at_cap_time_fraction = float((active_series >= cap).mean()) if len(active_series) else 0.0
    avg_active_exposure = float(avg_active_positions / max(cap, 1.0))

    if len(trades_df):
        gross_profit = float(trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum())
        gross_loss = float(-trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        win_rate = float((trades_df["pnl"] > 0).mean())
        expectancy_r = float(trades_df["r_multiple"].mean())
        hold_hours = (pd.to_datetime(trades_df["exit_time"]) - pd.to_datetime(trades_df["entry_time"])).dt.total_seconds() / 3600
        avg_hold_hours = float(hold_hours.mean())
        median_hold_hours = float(hold_hours.median())
        entry_notional = trades_df["entry_price"].astype(float) * trades_df["shares"].astype(float)
        exit_notional = trades_df["exit_price"].astype(float) * trades_df["shares"].astype(float)
        avg_equity = float(daily_eq.mean()) if len(daily_eq) else float(eq.mean())
        notional_turnover_over_avg_equity = float((entry_notional.sum() + exit_notional.sum()) / max(avg_equity, 1e-12))
        trades_per_day = float(len(trades_df) / max(len(daily_frame), 1))
        if "participation_rate" in trades_df.columns:
            part = trades_df["participation_rate"].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
            avg_participation_rate = float(part.mean()) if len(part) else 0.0
            p95_participation_rate = float(np.quantile(part, 0.95)) if len(part) else 0.0
        else:
            avg_participation_rate = 0.0
            p95_participation_rate = 0.0
        gross_positive_r = float(trades_df.loc[trades_df["r_multiple"] > 0, "r_multiple"].sum()) if "r_multiple" in trades_df.columns else 0.0
        estimated_cost_r_total = float(trades_df["estimated_cost_r"].sum()) if "estimated_cost_r" in trades_df.columns else 0.0
        gross_edge_to_round_trip_cost = float(gross_positive_r / estimated_cost_r_total) if estimated_cost_r_total > 1e-12 else 0.0
    else:
        profit_factor = 0.0
        win_rate = 0.0
        expectancy_r = 0.0
        avg_hold_hours = 0.0
        median_hold_hours = 0.0
        notional_turnover_over_avg_equity = 0.0
        trades_per_day = 0.0
        avg_participation_rate = 0.0
        p95_participation_rate = 0.0
        gross_edge_to_round_trip_cost = 0.0
    return {
        "n_trades": int(len(trades_df)),
        "total_return": total_return,
        "cagr": float(cagr),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "daily_cagr": float(daily_cagr),
        "daily_mdd": float(daily_mdd),
        "daily_calmar": float(daily_calmar),
        "sortino_daily": float(sortino_daily),
        "profit_factor": float(profit_factor),
        "win_rate": float(win_rate),
        "expectancy_r": float(expectancy_r),
        "avg_hold_hours": float(avg_hold_hours),
        "median_hold_hours": float(median_hold_hours),
        "ending_equity": float(eq.iloc[-1]),
        "sharpe": float(sharpe),
        "sharpe_daily_raw": float(daily_diag["sharpe_daily_raw"]),
        "adjusted_sharpe_daily": float(daily_diag["adjusted_sharpe_daily"]),
        "adjusted_sharpe_lag": int(daily_diag["adjusted_sharpe_lag"]),
        "n_daily_observations": int(daily_diag["n_daily_observations"]),
        "n_nonzero_return_days": int(daily_diag["n_nonzero_return_days"]),
        "notional_turnover_over_avg_equity": float(notional_turnover_over_avg_equity),
        "trades_per_day": float(trades_per_day),
        "avg_active_positions": float(avg_active_positions),
        "median_active_positions": float(median_active_positions),
        "p95_active_positions": float(p95_active_positions),
        "flat_time_fraction": float(flat_time_fraction),
        "at_cap_time_fraction": float(at_cap_time_fraction),
        "avg_active_exposure": float(avg_active_exposure),
        "avg_participation_rate": float(avg_participation_rate),
        "p95_participation_rate": float(p95_participation_rate),
        "gross_edge_to_round_trip_cost": float(gross_edge_to_round_trip_cost),
    }


def research_score(
    metrics: Dict[str, float],
    fold_expectancies: Sequence[float],
    top_ticker_share_abs: float,
) -> Tuple[float, Dict[str, float]]:
    n_trades = metrics["n_trades"]
    profit_factor = metrics["profit_factor"]
    expectancy_r = metrics["expectancy_r"]
    calmar = metrics["calmar"]
    mdd = metrics["mdd"]
    cagr = metrics["cagr"]
    churn = metrics.get("churn", 0.0)
    posfold = float(np.mean([x > 0 for x in fold_expectancies])) if len(fold_expectancies) else 0.0
    dispersion = float(np.std(fold_expectancies) / (abs(np.mean(fold_expectancies)) + 1e-6)) if len(fold_expectancies) else 0.0
    reject = (
        (n_trades < 75)
        or (profit_factor < 1.20)
        or (expectancy_r < 0.12)
        or (calmar < 0.80)
        or (mdd > 0.25)
        or (posfold < 0.65)
        or (top_ticker_share_abs > 0.35)
    )
    calmar_n = np.clip((calmar - 0.80) / (2.50 - 0.80), 0, 1)
    pf_n = np.clip((profit_factor - 1.20) / (2.00 - 1.20), 0, 1)
    exp_n = np.clip((expectancy_r - 0.12) / (0.30 - 0.12), 0, 1)
    cagr_n = np.clip((cagr - 0.12) / (0.35 - 0.12), 0, 1)
    stability_n = 0.5 * posfold + 0.5 * np.clip(1 - dispersion / 1.0, 0, 1)
    dd_p = np.clip((mdd - 0.15) / (0.25 - 0.15), 0, 1)
    churn_p = np.clip((churn - 0.10) / (0.30 - 0.10), 0, 1)
    conc_p = np.clip((top_ticker_share_abs - 0.20) / (0.35 - 0.20), 0, 1)
    score = 100 * (
        0.30 * calmar_n
        + 0.20 * pf_n
        + 0.25 * exp_n
        + 0.10 * cagr_n
        + 0.15 * stability_n
        - 0.10 * dd_p
        - 0.05 * churn_p
        - 0.05 * conc_p
    )
    if reject:
        score -= 100
    meta = {
        "posfold": posfold,
        "dispersion": dispersion,
        "top_ticker_share_abs": top_ticker_share_abs,
        "reject": float(reject),
    }
    return float(score), meta


def simulate_book(
    scored_df: pd.DataFrame,
    config: PipelineConfig,
    max_concurrent: int,
    p_min: float,
    theta_ev: float,
    theta_rel: float,
    fold_name: str,
    audit_sink: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    df = make_session_codes(scored_df).sort_values(["timestamp_utc", "ticker"]).copy()
    by_timestamp = {ts: g.copy() for ts, g in df.groupby("timestamp_utc", sort=True)}
    last_row_by_ticker = {
        str(ticker): group.sort_values("timestamp_utc").iloc[-1]
        for ticker, group in df.groupby("ticker", sort=False)
        if len(group)
    }
    timestamps = sorted(by_timestamp.keys())
    cash = config.starting_capital
    active: Dict[str, List[Position]] = defaultdict(list)
    pending: List[Dict[str, object]] = []
    trades: List[Dict[str, object]] = []
    equity_curve: List[Dict[str, object]] = []
    replacement_exits = 0
    capacity_clipped_orders = 0
    capacity_skipped_orders = 0
    capacity_requested_notional = 0.0
    capacity_executed_notional = 0.0
    capacity_clipped_pnl_drag = 0.0

    def append_audit(decision: str, row_like: Mapping[str, Any], **extra: Any) -> None:
        if audit_sink is None:
            return
        audit_sink.append(
            {
                "fold": fold_name,
                "timestamp_utc": str(row_like.get("timestamp_utc", "")),
                "ticker": str(row_like.get("ticker", "")),
                "decision": decision,
                "max_concurrent": int(max_concurrent),
                "p_cal": float(row_like.get("p_cal", np.nan)),
                "p_empirical": float(row_like.get("p_empirical", row_like.get("p_cal", np.nan))),
                "ev_empirical_r": float(row_like.get("ev_empirical_r", np.nan)),
                "cost_est_r": float(row_like.get("cost_est_r", np.nan)),
                "signal_dollar_volume": float(row_like.get("signal_dollar_volume", np.nan)),
                "signal_adv_dollar_20": float(row_like.get("signal_adv_dollar_20", np.nan)),
                **extra,
            }
        )

    def total_active_positions() -> int:
        return sum(len(v) for v in active.values())

    def total_open_slots() -> int:
        return total_active_positions() + len(pending)

    def ticker_open_slots(ticker: str) -> int:
        return len(active.get(ticker, [])) + sum(1 for x in pending if x.get("ticker") == ticker)

    def mark_equity(group: pd.DataFrame) -> float:
        close_map = group.set_index("ticker")["close"].to_dict()
        mv = 0.0
        for ticker, positions in active.items():
            mark_px = close_map.get(ticker, np.nan)
            for pos in positions:
                mv += pos.shares * (float(mark_px) if np.isfinite(mark_px) else pos.entry_reference_price)
        return cash + mv

    for ts in timestamps:
        group = by_timestamp[ts].sort_values("ticker")

        # Pending orders are valid for the next open only; if we cannot fill this bar, the order expires.
        for order in pending:
            ticker = str(order["ticker"])
            row_match = group[group["ticker"] == ticker]
            if row_match.empty:
                continue
            if total_active_positions() >= max_concurrent:
                continue
            if ticker_open_slots(ticker) >= config.max_positions_per_ticker:
                continue
            row = row_match.iloc[0]
            entry = float(row["open"])
            atr = float(row["atr_14"])
            if not (np.isfinite(entry) and np.isfinite(atr) and entry > 0 and atr > 0):
                continue
            sizing_equity = float(cast(Any, order.get("sizing_equity", config.starting_capital)))
            risk_budget = config.risk_per_trade * max(sizing_equity, 0.0)
            risk_per_share = config.stop_atr_multiple * atr
            if risk_per_share <= 0:
                continue
            requested_shares = int(math.floor(risk_budget / risk_per_share))
            affordable = int(math.floor(cash / (entry * (1 + config.slippage_per_fill)))) if entry > 0 else 0
            requested_shares = max(0, min(requested_shares, affordable))
            if requested_shares <= 0:
                continue
            exec_px = entry * (1 + config.slippage_per_fill)
            requested_notional = requested_shares * exec_px
            capacity_requested_notional += requested_notional
            signal_adv_dollar_20 = float(cast(Any, order.get("signal_adv_dollar_20", np.nan)))
            max_shares_capacity = requested_shares
            capacity_clipped = 0
            projected_participation = np.nan
            if np.isfinite(signal_adv_dollar_20) and signal_adv_dollar_20 > 0:
                max_notional_capacity = config.max_adv_participation * signal_adv_dollar_20
                max_shares_capacity = int(math.floor(max_notional_capacity / max(exec_px, 1e-12)))
                projected_participation = requested_notional / signal_adv_dollar_20 if signal_adv_dollar_20 > 0 else np.nan
            else:
                max_shares_capacity = 0
            shares = max(0, min(requested_shares, max_shares_capacity))
            if shares <= 0:
                capacity_skipped_orders += 1
                append_audit("capacity_skipped", cast(Mapping[str, Any], order), requested_shares=int(requested_shares))
                continue
            if shares < requested_shares:
                capacity_clipped = 1
                capacity_clipped_orders += 1
                append_audit(
                    "capacity_clipped_entered",
                    cast(Mapping[str, Any], order),
                    requested_shares=int(requested_shares),
                    executed_shares=int(shares),
                )
            else:
                append_audit(
                    "entered",
                    cast(Mapping[str, Any], order),
                    requested_shares=int(requested_shares),
                    executed_shares=int(shares),
                )
            cash -= shares * exec_px
            executed_notional = shares * exec_px
            capacity_executed_notional += executed_notional
            active[ticker].append(
                Position(
                    ticker=ticker,
                    entry_signal_time=pd.Timestamp(order["timestamp_utc"]),
                    entry_execution_time=pd.Timestamp(ts),
                    entry_exec_price=exec_px,
                    entry_reference_price=entry,
                    stop_price=entry - config.stop_atr_multiple * atr,
                    target_price=entry + config.target_atr_multiple * atr,
                    shares=shares,
                    entry_session_code=int(cast(Any, row["session_code"])),
                    p_entry=float(cast(Any, order["p_cal"])),
                    p_empirical_entry=float(cast(Any, order.get("p_empirical", order["p_cal"]))),
                    ev_entry_r=float(cast(Any, order.get("ev_empirical_r", np.nan))),
                    estimated_cost_r=float(cast(Any, order["cost_est_r"])),
                    entry_row_idx=int(row["ticker_row_idx"]),
                    entry_regime_label=str(cast(Any, order.get("entry_regime_label", "unknown"))),
                    requested_shares=int(requested_shares),
                    requested_notional=float(requested_notional),
                    signal_dollar_volume=float(cast(Any, order.get("signal_dollar_volume", np.nan))),
                    signal_adv_dollar_20=float(signal_adv_dollar_20),
                    projected_participation=float(executed_notional / signal_adv_dollar_20) if np.isfinite(signal_adv_dollar_20) and signal_adv_dollar_20 > 0 else np.nan,
                    capacity_clipped=int(capacity_clipped),
                )
            )
        pending = []

        for _, row in group.iterrows():
            ticker = str(row["ticker"])
            if ticker not in active or not active[ticker]:
                continue
            survivors: List[Position] = []
            low = float(cast(Any, row["low"]))
            high = float(cast(Any, row["high"]))
            close = float(cast(Any, row["close"]))
            for pos in active[ticker]:
                reason = None
                exit_px = None
                if low <= pos.stop_price and high >= pos.target_price:
                    reason = "ambiguous_stop_first"
                    exit_px = pos.stop_price * (1 - config.slippage_per_fill)
                elif low <= pos.stop_price:
                    reason = "stop"
                    exit_px = pos.stop_price * (1 - config.slippage_per_fill)
                elif high >= pos.target_price:
                    reason = "target"
                    exit_px = pos.target_price * (1 - config.slippage_per_fill)
                elif (int(row["ticker_row_idx"]) - int(pos.entry_row_idx)) >= (config.max_horizon_bars - 1):
                    reason = "time"
                    exit_px = close * (1 - config.slippage_per_fill)
                if reason is None:
                    survivors.append(pos)
                    continue
                assert exit_px is not None
                entry_notional = pos.entry_exec_price * pos.shares
                overnights = max(0, int(row["session_code"]) - pos.entry_session_code)
                carry = entry_notional * config.overnight_brokerage * overnights
                proceeds = pos.shares * exit_px - carry
                cash += proceeds
                pnl = proceeds - entry_notional
                denom = (pos.entry_reference_price - pos.stop_price) * pos.shares
                r_multiple = pnl / denom if denom > 0 else np.nan
                if pos.capacity_clipped and pos.shares > 0:
                    capacity_clipped_pnl_drag += float((pos.requested_shares - pos.shares) * (pnl / pos.shares))
                trades.append({
                    "fold": fold_name,
                    "ticker": ticker,
                    "entry_signal_time": pos.entry_signal_time,
                    "entry_time": pos.entry_execution_time,
                    "exit_time": ts,
                    "entry_price": pos.entry_exec_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "reason": reason,
                    "p_entry": pos.p_entry,
                    "p_empirical_entry": pos.p_empirical_entry,
                    "ev_entry_r": pos.ev_entry_r,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "overnights": overnights,
                    "replacement_exit": 0,
                    "entry_regime_label": pos.entry_regime_label,
                    "requested_shares": pos.requested_shares,
                    "requested_notional": pos.requested_notional,
                    "signal_dollar_volume": pos.signal_dollar_volume,
                    "signal_adv_dollar_20": pos.signal_adv_dollar_20,
                    "participation_rate": pos.projected_participation,
                    "capacity_clipped": pos.capacity_clipped,
                })
            if survivors:
                active[ticker] = survivors
            else:
                del active[ticker]

        current_equity = mark_equity(group)
        reward_r = config.target_atr_multiple / max(config.stop_atr_multiple, 1e-12)
        candidates: List[Dict[str, object]] = []
        for _, row in group.iterrows():
            ticker = str(row["ticker"])
            if ticker_open_slots(ticker) >= config.max_positions_per_ticker:
                continue
            if pd.isna(row.get("next_timestamp_utc")):
                continue
            p = float(row.get("p_empirical", row["p_cal"]))
            if not np.isfinite(p) or p < p_min:
                continue
            atr = float(row["atr_14"])
            entry = float(row["entry_open_next"])
            cost_r = float(row["cost_est_r"])
            if not (np.isfinite(atr) and atr > 0 and np.isfinite(entry) and entry > 0 and np.isfinite(cost_r)):
                continue
            ev_r = float(row.get("ev_empirical_r", p * reward_r - (1.0 - p) - cost_r))
            if ev_r <= 0:
                continue
            signal_close = float(row["close"]) if np.isfinite(float(row["close"])) else np.nan
            signal_volume = float(row["volume"]) if np.isfinite(float(row["volume"])) else np.nan
            signal_dollar_volume = signal_close * signal_volume if np.isfinite(signal_close) and np.isfinite(signal_volume) else np.nan
            rel_volume_20 = float(row.get("rel_volume_20", np.nan))
            signal_adv_dollar_20 = (
                signal_dollar_volume / rel_volume_20
                if np.isfinite(signal_dollar_volume) and np.isfinite(rel_volume_20) and rel_volume_20 > 0
                else np.nan
            )
            row_dict = row.to_dict()
            row_dict["signal_dollar_volume"] = signal_dollar_volume
            row_dict["signal_adv_dollar_20"] = signal_adv_dollar_20
            row_dict["entry_regime_label"] = str(row.get("entry_regime_label", "unknown"))
            candidates.append({"ticker": ticker, "row": row_dict, "ev_r": float(ev_r), "p": p})
        candidates.sort(key=lambda x: (x["ev_r"], x["p"]), reverse=True)

        for cand in candidates:
            ticker = str(cand["ticker"])
            if ticker_open_slots(ticker) >= config.max_positions_per_ticker:
                continue
            if total_open_slots() < max_concurrent:
                pending.append({**cast(Dict[str, Any], cand["row"]), "sizing_equity": current_equity})
                append_audit("queued_pending", cast(Mapping[str, Any], cand["row"]), queue_reason="slot_available")
                continue
            incumbent_scores: List[Tuple[str, int, float]] = []
            for inc_ticker, positions in active.items():
                row_match = group[group["ticker"] == inc_ticker]
                if row_match.empty:
                    continue
                inc_row = row_match.iloc[0]
                close_inc = float(inc_row["close"])
                p_now_raw = float(inc_row.get("p_empirical", inc_row["p_cal"]))
                p_now = p_now_raw if np.isfinite(p_now_raw) else positions[0].p_empirical_entry
                for pos_idx, pos in enumerate(positions):
                    risk_per_share = max(pos.entry_reference_price - pos.stop_price, 1e-12)
                    remaining_profit_r = max(pos.target_price - close_inc, 0.0) / risk_per_share
                    remaining_loss_r = max(close_inc - pos.stop_price, 0.0) / risk_per_share
                    remaining_cost_r = (
                        close_inc * (2 * config.slippage_per_fill + config.estimated_overnights_for_ranking * config.overnight_brokerage)
                    ) / risk_per_share
                    ev_remaining_r = p_now * remaining_profit_r - (1.0 - p_now) * remaining_loss_r - remaining_cost_r
                    incumbent_scores.append((inc_ticker, pos_idx, float(ev_remaining_r)))
            if not incumbent_scores:
                continue
            weakest_ticker, weakest_pos_idx, weakest_ev_r = min(incumbent_scores, key=lambda x: x[2])
            cand_ev_r = float(cast(Any, cand["ev_r"]))
            # Replacement rule: positive-EV candidates can replace incumbents. If weakest incumbent has
            # positive EV use additive + relative hurdle; if non-positive EV, theta_rel * weakest_ev_r
            # is meaningless so use absolute hurdle only.
            if weakest_ev_r > 0:
                replace = cand_ev_r > weakest_ev_r + theta_ev and cand_ev_r > theta_rel * weakest_ev_r
            else:
                replace = cand_ev_r > theta_ev
            if replace:
                row = group[group["ticker"] == weakest_ticker].iloc[0]
                pos = active[weakest_ticker].pop(weakest_pos_idx)
                if not active[weakest_ticker]:
                    del active[weakest_ticker]
                exit_px = float(row["close"]) * (1 - config.slippage_per_fill)
                entry_notional = pos.entry_exec_price * pos.shares
                overnights = max(0, int(row["session_code"]) - pos.entry_session_code)
                carry = entry_notional * config.overnight_brokerage * overnights
                proceeds = pos.shares * exit_px - carry
                cash += proceeds
                pnl = proceeds - entry_notional
                denom = (pos.entry_reference_price - pos.stop_price) * pos.shares
                r_multiple = pnl / denom if denom > 0 else np.nan
                if pos.capacity_clipped and pos.shares > 0:
                    capacity_clipped_pnl_drag += float((pos.requested_shares - pos.shares) * (pnl / pos.shares))
                trades.append({
                    "fold": fold_name,
                    "ticker": weakest_ticker,
                    "entry_signal_time": pos.entry_signal_time,
                    "entry_time": pos.entry_execution_time,
                    "exit_time": ts,
                    "entry_price": pos.entry_exec_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "reason": "replacement",
                    "p_entry": pos.p_entry,
                    "p_empirical_entry": pos.p_empirical_entry,
                    "ev_entry_r": pos.ev_entry_r,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "overnights": overnights,
                    "replacement_exit": 1,
                    "entry_regime_label": pos.entry_regime_label,
                    "requested_shares": pos.requested_shares,
                    "requested_notional": pos.requested_notional,
                    "signal_dollar_volume": pos.signal_dollar_volume,
                    "signal_adv_dollar_20": pos.signal_adv_dollar_20,
                    "participation_rate": pos.projected_participation,
                    "capacity_clipped": pos.capacity_clipped,
                })
                replacement_exits += 1
                if total_open_slots() < max_concurrent and ticker_open_slots(ticker) < config.max_positions_per_ticker:
                    pending.append({**cast(Dict[str, Any], cand["row"]), "sizing_equity": current_equity})
                    append_audit(
                        "queued_after_replacement",
                        cast(Mapping[str, Any], cand["row"]),
                        replaced_ticker=str(weakest_ticker),
                        replaced_ev_r=float(weakest_ev_r),
                    )
            else:
                append_audit(
                    "rejected_no_replacement",
                    cast(Mapping[str, Any], cand["row"]),
                    weakest_ticker=str(weakest_ticker),
                    weakest_ev_r=float(weakest_ev_r),
                )

        equity_curve.append(
            {
                "timestamp_utc": ts,
                "equity": mark_equity(group),
                "active_positions": int(total_active_positions()),
            }
        )

    if timestamps:
        final_ts = timestamps[-1]
        group = by_timestamp[final_ts]
        for ticker, positions in list(active.items()):
            ticker_rows = group[group["ticker"] == ticker]
            row = ticker_rows.iloc[0] if len(ticker_rows) else last_row_by_ticker.get(str(ticker))
            if row is None:
                continue
            for pos in positions:
                exit_px = float(row["close"]) * (1 - config.slippage_per_fill)
                entry_notional = pos.entry_exec_price * pos.shares
                overnights = max(0, int(row["session_code"]) - pos.entry_session_code)
                carry = entry_notional * config.overnight_brokerage * overnights
                proceeds = pos.shares * exit_px - carry
                cash += proceeds
                pnl = proceeds - entry_notional
                denom = (pos.entry_reference_price - pos.stop_price) * pos.shares
                r_multiple = pnl / denom if denom > 0 else np.nan
                if pos.capacity_clipped and pos.shares > 0:
                    capacity_clipped_pnl_drag += float((pos.requested_shares - pos.shares) * (pnl / pos.shares))
                trades.append({
                    "fold": fold_name,
                    "ticker": ticker,
                    "entry_signal_time": pos.entry_signal_time,
                    "entry_time": pos.entry_execution_time,
                    "exit_time": final_ts,
                    "entry_price": pos.entry_exec_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "reason": "forced_end",
                    "p_entry": pos.p_entry,
                    "p_empirical_entry": pos.p_empirical_entry,
                    "ev_entry_r": pos.ev_entry_r,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "overnights": overnights,
                    "replacement_exit": 0,
                    "entry_regime_label": pos.entry_regime_label,
                    "requested_shares": pos.requested_shares,
                    "requested_notional": pos.requested_notional,
                    "signal_dollar_volume": pos.signal_dollar_volume,
                    "signal_adv_dollar_20": pos.signal_adv_dollar_20,
                    "participation_rate": pos.projected_participation,
                    "capacity_clipped": pos.capacity_clipped,
                })
            del active[ticker]
        equity_curve.append({"timestamp_utc": final_ts, "equity": cash, "active_positions": 0})

    trades_df = pd.DataFrame(trades)
    equity_df = (
        pd.DataFrame(equity_curve)
        .drop_duplicates(subset=["timestamp_utc"], keep="last")
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )
    metrics = compute_metrics(trades_df, equity_df, config)
    metrics["replacement_exits"] = int(replacement_exits)
    metrics["total_exits"] = int(len(trades_df))
    metrics["churn"] = float(replacement_exits / max(len(trades_df), 1))
    metrics["capacity_clipped_orders"] = int(capacity_clipped_orders)
    metrics["capacity_skipped_orders"] = int(capacity_skipped_orders)
    metrics["capacity_requested_notional"] = float(capacity_requested_notional)
    metrics["capacity_executed_notional"] = float(capacity_executed_notional)
    metrics["capacity_notional_reduction"] = float(max(capacity_requested_notional - capacity_executed_notional, 0.0))
    metrics["capacity_clipped_pnl_drag"] = float(capacity_clipped_pnl_drag)
    return trades_df, equity_df, metrics


# ============================================================
# THRESHOLD SELECTION
# ============================================================
def choose_thresholds(
    holdout_scored: pd.DataFrame,
    config: PipelineConfig,
    fold_name: str,
    max_concurrent: int,
) -> Tuple[Dict[str, float], pd.DataFrame, Dict[str, Any]]:
    """Select (p_min, theta_ev, theta_rel) by grid search on holdout_scored and evaluate
    within-family WRC on the threshold search family."""
    best_score = -np.inf
    best_bundle: Optional[Dict[str, float]] = None
    session_dates = session_dates_from_frame(holdout_scored)
    candidate_rows: List[Dict[str, Any]] = []
    candidate_returns: List[np.ndarray] = []
    for p_min in config.p_min_grid:
        for theta_ev in config.theta_ev_grid:
            for theta_rel in config.theta_rel_grid:
                trades, equity, metrics = simulate_book(
                    holdout_scored,
                    config=config,
                    max_concurrent=max_concurrent,
                    p_min=p_min,
                    theta_ev=theta_ev,
                    theta_rel=theta_rel,
                    fold_name=f"{fold_name}_train_slots_{max_concurrent}",
                )
                if len(trades):
                    per_ticker = trades.groupby("ticker")["pnl"].sum().abs()
                    top_share_abs = float(per_ticker.max() / per_ticker.sum()) if per_ticker.sum() > 0 else 1.0
                    tmp = trades.copy()
                    tmp["stability_bucket"] = pd.to_datetime(tmp["entry_time"], utc=True).dt.tz_convert(None).dt.to_period("Q")
                    fold_expectancies = tmp.groupby("stability_bucket")["r_multiple"].mean().tolist()
                else:
                    top_share_abs = 1.0
                    fold_expectancies = []
                score, meta = research_score(metrics, fold_expectancies, top_share_abs)
                daily_frame = build_daily_equity_frame(equity, session_dates, config.starting_capital, max_concurrent)
                daily_diag = compute_daily_return_diagnostics(daily_frame["daily_return"].tolist())
                candidate_returns.append(daily_frame["daily_return"].astype(float).to_numpy())
                bundle = {
                    "p_min": float(p_min),
                    "theta_ev": float(theta_ev),
                    "theta_rel": float(theta_rel),
                    "score": float(score),
                    **metrics,
                    **meta,
                }
                candidate_rows.append(
                    {
                        "fold": fold_name,
                        "max_concurrent": int(max_concurrent),
                        "p_min": float(p_min),
                        "theta_ev": float(theta_ev),
                        "theta_rel": float(theta_rel),
                        "threshold_score": float(score),
                        "n_trades": int(metrics["n_trades"]),
                        "n_daily_observations": int(daily_diag["n_daily_observations"]),
                        "n_nonzero_return_days": int(daily_diag["n_nonzero_return_days"]),
                        "avg_active_exposure": float(metrics.get("avg_active_exposure", 0.0)),
                        "adjusted_sharpe_daily": float(daily_diag["adjusted_sharpe_daily"]),
                        "sharpe_daily_raw": float(daily_diag["sharpe_daily_raw"]),
                        "profit_factor": float(metrics["profit_factor"]),
                        "daily_calmar": float(metrics.get("daily_calmar", 0.0)),
                        "expectancy_r": float(metrics["expectancy_r"]),
                    }
                )
                if score > best_score:
                    best_score = score
                    best_bundle = bundle
                    logging.info(
                        "Threshold NEW BEST | fold=%s | slots=%s | p=%.2f | tev=%.2f | trel=%.2f | score=%.2f | n=%s | pf=%.2f | exp_r=%.3f",
                        fold_name, max_concurrent, p_min, theta_ev, theta_rel, score,
                        metrics["n_trades"], metrics["profit_factor"], metrics["expectancy_r"],
                    )
                else:
                    logging.info(
                        "Threshold eval | fold=%s | slots=%s | p=%.2f | tev=%.2f | trel=%.2f | score=%.2f | n=%s | pf=%.2f | exp_r=%.3f",
                        fold_name, max_concurrent, p_min, theta_ev, theta_rel, score,
                        metrics["n_trades"], metrics["profit_factor"], metrics["expectancy_r"],
                    )
    assert best_bundle is not None
    candidate_df = pd.DataFrame(candidate_rows)
    best_mask = (
        (candidate_df["p_min"] == float(best_bundle["p_min"]))
        & (candidate_df["theta_ev"] == float(best_bundle["theta_ev"]))
        & (candidate_df["theta_rel"] == float(best_bundle["theta_rel"]))
    ) if len(candidate_df) else pd.Series(dtype=bool)
    if len(candidate_df):
        candidate_df["selected_threshold_tuple"] = best_mask.astype(int)
    selected_row = candidate_df.loc[best_mask].iloc[0].to_dict() if len(candidate_df) and best_mask.any() else {}
    sufficient = (
        float(selected_row.get("n_daily_observations", 0)) >= config.threshold_wrc_min_daily_observations
        and float(selected_row.get("n_nonzero_return_days", 0)) >= config.threshold_wrc_min_nonzero_days
        and float(selected_row.get("n_trades", 0)) >= config.threshold_wrc_min_trades
        and float(selected_row.get("avg_active_exposure", 0.0)) >= config.threshold_wrc_min_avg_active_exposure
    )
    candidate_count = int(len(candidate_df))
    formal_trial_count = threshold_policy_trial_count(config)
    wrc_summary: Dict[str, Any] = {
        "wrc_status": "insufficient_data",
        "wrc_pvalue": np.nan,
        "wrc_pass": 0,
        "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
        "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
        "trial_scope_formal": TRIAL_SCOPE_FORMAL,
        "trial_count_formal": int(formal_trial_count),
        "threshold_family_candidate_count": int(candidate_count),
        "threshold_wrc_alpha": float(config.threshold_wrc_alpha),
        "threshold_wrc_block_length": int(config.threshold_wrc_block_length),
        "threshold_wrc_bootstrap_reps": int(config.threshold_wrc_bootstrap_reps),
        "wrc_min_daily_observations": int(config.threshold_wrc_min_daily_observations),
        "wrc_min_nonzero_days": int(config.threshold_wrc_min_nonzero_days),
        "wrc_min_trades": int(config.threshold_wrc_min_trades),
        "wrc_min_avg_active_exposure": float(config.threshold_wrc_min_avg_active_exposure),
        "wrc_selected_n_daily_observations": int(selected_row.get("n_daily_observations", 0) or 0),
        "wrc_selected_n_nonzero_return_days": int(selected_row.get("n_nonzero_return_days", 0) or 0),
        "wrc_selected_n_trades": int(selected_row.get("n_trades", 0) or 0),
        "wrc_selected_avg_active_exposure": float(selected_row.get("avg_active_exposure", 0.0) or 0.0),
    }
    if candidate_returns and sufficient:
        threshold_wrc_seed = int(config.random_seed + deterministic_seed_from_text(fold_name))
        return_matrix = np.column_stack(candidate_returns)
        wrc_result = moving_block_bootstrap_white_reality_check(
            return_matrix,
            block_length=config.threshold_wrc_block_length,
            bootstrap_reps=config.threshold_wrc_bootstrap_reps,
            random_seed=threshold_wrc_seed,
        )
        wrc_summary.update(wrc_result)
        wrc_summary["threshold_wrc_seed"] = int(threshold_wrc_seed)
        wrc_summary["wrc_status"] = "pass" if float(wrc_result["wrc_pvalue"]) <= config.threshold_wrc_alpha else "fail"
        wrc_summary["wrc_pass"] = int(float(wrc_result["wrc_pvalue"]) <= config.threshold_wrc_alpha)
    else:
        wrc_summary["threshold_wrc_seed"] = int(config.random_seed + deterministic_seed_from_text(fold_name))
    if len(candidate_df):
        for key, value in wrc_summary.items():
            candidate_df[key] = value
        candidate_df["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
        candidate_df["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
        candidate_df["schema_version"] = SCHEMA_VERSION
        candidate_df["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
        candidate_df["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
        candidate_df["implementation_status"] = config.implementation_status
        candidate_df["verification_stage_reached"] = config.verification_stage_reached
    return best_bundle, candidate_df, wrc_summary


def chain_equity_curves(equity_df: pd.DataFrame, max_concurrent: int, starting_capital: float) -> pd.DataFrame:
    if len(equity_df) == 0:
        return pd.DataFrame(columns=["timestamp_utc", "equity", "max_concurrent", "fold"])
    pieces: List[pd.DataFrame] = []
    capital = float(starting_capital)
    folds = sorted(equity_df.loc[equity_df["max_concurrent"] == max_concurrent, "fold"].drop_duplicates().tolist())
    for fold in folds:
        g = equity_df[(equity_df["max_concurrent"] == max_concurrent) & (equity_df["fold"] == fold)].copy()
        if len(g) == 0:
            continue
        g = g.sort_values("timestamp_utc").reset_index(drop=True)
        base = float(g["equity"].iloc[0])
        if base <= 0:
            continue
        g["equity"] = capital * (g["equity"].astype(float) / base)
        capital = float(g["equity"].iloc[-1])
        pieces.append(g)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(
        columns=["timestamp_utc", "equity", "max_concurrent", "fold"]
    )


def fit_linear_baseline_scored(
    fit_df: pd.DataFrame,
    score_df: pd.DataFrame,
    features: Sequence[str],
    config: PipelineConfig,
    seed: int,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    usable = [feature for feature in features if feature in fit_df.columns and feature in score_df.columns]
    fit_scored = fit_df.copy()
    out = score_df.copy()
    meta = {"baseline_feature_count": int(len(usable)), "baseline_status": "ok"}
    if len(usable) < 2 or len(fit_df) == 0 or fit_df["long_win"].nunique() < 2:
        fit_scored["p_cal"] = 0.5
        out["p_cal"] = 0.5
        fit_scored["cost_est_r"] = estimate_cost_r_from_frame(fit_scored, config)
        out["cost_est_r"] = estimate_cost_r_from_frame(out, config)
        fit_scored, out, empirical_meta = apply_empirical_probability_map(fit_scored, out, config)
        meta["baseline_status"] = "fallback_constant"
        meta.update(empirical_meta)
        return out, meta
    X_fit, X_score, _ = impute_fit_transform(fit_df[usable], score_df[usable])
    model = LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        max_iter=2000,
        class_weight="balanced",
        random_state=int(seed),
    )
    model.fit(X_fit, fit_df["long_win"].astype(int).values)
    fit_scored["p_cal"] = clip_prob(model.predict_proba(X_fit)[:, 1])
    out["p_cal"] = clip_prob(model.predict_proba(X_score)[:, 1])
    fit_scored["cost_est_r"] = estimate_cost_r_from_frame(fit_scored, config)
    out["cost_est_r"] = estimate_cost_r_from_frame(out, config)
    fit_scored, out, empirical_meta = apply_empirical_probability_map(fit_scored, out, config)
    meta.update(empirical_meta)
    return out, meta


def _select_equal_weight_rank_features(
    candidate_features: Sequence[str],
    feature_family_map: Mapping[str, Any],
    max_features: int = 8,
) -> List[str]:
    selected: List[str] = []
    seen_families: set[str] = set()
    for feature in candidate_features:
        family = str(feature_family_map.get(feature, "unknown"))
        if family in seen_families:
            continue
        selected.append(feature)
        seen_families.add(family)
        if len(selected) >= max_features:
            break
    return selected


def _infer_feature_direction(
    fit_df: pd.DataFrame,
    feature_name: str,
    expected_sign: str,
) -> int:
    if str(expected_sign).lower().startswith("neg"):
        return -1
    if str(expected_sign).lower().startswith("pos"):
        return 1
    if feature_name not in fit_df.columns or "forward_label_return_net" not in fit_df.columns:
        return 1
    subset = fit_df[[feature_name, "forward_label_return_net"]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(subset) < 10:
        return 1
    corr = subset[feature_name].corr(subset["forward_label_return_net"], method="spearman")
    return -1 if np.isfinite(corr) and float(corr) < 0 else 1


def fit_equal_weight_rank_blend_scored(
    fit_df: pd.DataFrame,
    score_df: pd.DataFrame,
    candidate_features: Sequence[str],
    feature_registry_df: pd.DataFrame,
    feature_family_map: Mapping[str, Any],
    config: PipelineConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    selected = _select_equal_weight_rank_features(candidate_features, feature_family_map, max_features=8)
    fit_scored = fit_df.copy()
    out = score_df.copy()
    if not selected:
        fit_scored["p_cal"] = 0.5
        out["p_cal"] = 0.5
        fit_scored["cost_est_r"] = estimate_cost_r_from_frame(fit_scored, config)
        out["cost_est_r"] = estimate_cost_r_from_frame(out, config)
        fit_scored, out, empirical_meta = apply_empirical_probability_map(fit_scored, out, config)
        meta = {
            "baseline_feature_count": 0,
            "baseline_status": "fallback_constant",
            "selected_features_json": json.dumps([]),
        }
        meta.update(empirical_meta)
        return out, meta
    registry = feature_registry_df.set_index("feature_name").to_dict("index") if len(feature_registry_df) else {}
    directions = {
        feature: _infer_feature_direction(
            fit_df,
            feature,
            str(registry.get(feature, {}).get("expected_sign", "mixed")),
        )
        for feature in selected
    }

    def _blend_scores(frame: pd.DataFrame) -> pd.Series:
        parts: List[pd.Series] = []
        for feature in selected:
            if feature not in frame.columns:
                continue
            adjusted = winsorize_series(frame[feature].astype(float)) * directions[feature]
            parts.append(_pct_rank_by_timestamp(adjusted, frame["timestamp_utc"]))
        if not parts:
            return pd.Series(np.full(len(frame), 0.5), index=frame.index, dtype=float)
        stack = pd.concat(parts, axis=1)
        return stack.mean(axis=1).fillna(0.5)

    fit_scores = _blend_scores(fit_df).astype(float)
    score_scores = _blend_scores(score_df).astype(float)
    fit_scored["p_cal"] = clip_prob(fit_scores.to_numpy(dtype=float))
    sorted_fit = np.sort(fit_scores.to_numpy(dtype=float))
    if len(sorted_fit) == 0:
        out["p_cal"] = 0.5
        status = "fallback_constant"
    else:
        probs = np.searchsorted(sorted_fit, score_scores.to_numpy(dtype=float), side="right") / len(sorted_fit)
        out["p_cal"] = clip_prob(np.asarray(probs, dtype=float))
        status = "ok"
    fit_scored["cost_est_r"] = estimate_cost_r_from_frame(fit_scored, config)
    out["cost_est_r"] = estimate_cost_r_from_frame(out, config)
    fit_scored, out, empirical_meta = apply_empirical_probability_map(fit_scored, out, config)
    meta = {
        "baseline_feature_count": int(len(selected)),
        "baseline_status": status,
        "selected_features_json": json.dumps(selected),
    }
    meta.update(empirical_meta)
    return out, meta


def evaluate_model_contender(
    contender_name: str,
    fold_name: str,
    threshold_holdout_scored: pd.DataFrame,
    test_scored: pd.DataFrame,
    test_df: pd.DataFrame,
    config: PipelineConfig,
) -> Dict[str, Any]:
    best_bundle, _, wrc_summary = choose_thresholds(
        threshold_holdout_scored,
        config,
        f"{fold_name}_{contender_name}",
        max_concurrent=int(config.max_concurrent_options[0]),
    )
    fold_selected = int(wrc_summary.get("wrc_pass", 0) == 1)
    fold_skip_reason = "" if fold_selected else str(wrc_summary.get("wrc_status", "wrc_fail"))
    session_dates = session_dates_from_frame(test_df)
    if fold_selected:
        trades, equity, metrics = simulate_book(
            test_scored,
            config=config,
            max_concurrent=int(config.max_concurrent_options[0]),
            p_min=float(best_bundle["p_min"]),
            theta_ev=float(best_bundle["theta_ev"]),
            theta_rel=float(best_bundle["theta_rel"]),
            fold_name=f"{fold_name}_{contender_name}_slots_{int(config.max_concurrent_options[0])}",
        )
        daily_frame = build_daily_equity_frame(
            equity,
            session_dates,
            config.starting_capital,
            int(config.max_concurrent_options[0]),
        )
    else:
        trades = pd.DataFrame()
        metrics = compute_metrics(pd.DataFrame(), pd.DataFrame(), config)
        daily_frame = build_daily_equity_frame(
            pd.DataFrame(),
            session_dates,
            config.starting_capital,
            int(config.max_concurrent_options[0]),
        )
    daily_diag = compute_daily_return_diagnostics(daily_frame["daily_return"].tolist())
    return {
        "fold": fold_name,
        "model_name": contender_name,
        "max_concurrent": int(config.max_concurrent_options[0]),
        "fold_selected": int(fold_selected),
        "fold_skip_reason": fold_skip_reason,
        "wrc_status": str(wrc_summary.get("wrc_status", "")),
        "wrc_pvalue": float(wrc_summary.get("wrc_pvalue", np.nan)),
        "adjusted_oos_sharpe": float(daily_diag.get("adjusted_sharpe_daily", 0.0)),
        "net_oos_spread_after_costs": float(metrics.get("expectancy_r", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "max_drawdown": float(metrics.get("daily_mdd", metrics.get("mdd", 0.0))),
        "calmar": float(metrics.get("daily_calmar", metrics.get("calmar", 0.0))),
        "turnover_notional_to_equity": float(metrics.get("turnover_notional_to_avg_equity", 0.0)),
        "capacity_drag_fraction_of_gross_alpha": float(metrics.get("capacity_drag_fraction_of_gross_alpha", 0.0)),
        "n_trades": int(metrics.get("n_trades", len(trades))),
        "n_daily_observations": int(daily_diag.get("n_daily_observations", 0)),
        "schema_version": SCHEMA_VERSION,
        "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
        "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
    }


def build_model_comparison_report(model_rows: pd.DataFrame) -> pd.DataFrame:
    if model_rows.empty:
        return pd.DataFrame(columns=MODEL_COMPARISON_REPORT_COLUMNS)
    report = (
        model_rows.groupby("model_name", as_index=False)
        .agg(
            folds_seen=("fold", "nunique"),
            selected_fold_fraction=("fold_selected", "mean"),
            mean_adjusted_oos_sharpe=("adjusted_oos_sharpe", "mean"),
            mean_net_oos_spread_after_costs=("net_oos_spread_after_costs", "mean"),
            mean_profit_factor=("profit_factor", "mean"),
            mean_calmar=("calmar", "mean"),
            mean_max_drawdown=("max_drawdown", "mean"),
            mean_turnover_notional_to_equity=("turnover_notional_to_equity", "mean"),
            mean_capacity_drag_fraction_of_gross_alpha=("capacity_drag_fraction_of_gross_alpha", "mean"),
            total_trades=("n_trades", "sum"),
        )
    )
    baseline_report = report[report["model_name"] != "incumbent_ml"]
    baseline_best = float(baseline_report["mean_adjusted_oos_sharpe"].max()) if len(baseline_report) else 0.0
    baseline_drawdown = float(baseline_report["mean_max_drawdown"].min()) if len(baseline_report) else math.inf
    baseline_turnover = float(baseline_report["mean_turnover_notional_to_equity"].min()) if len(baseline_report) else math.inf
    baseline_capacity_drag = (
        float(baseline_report["mean_capacity_drag_fraction_of_gross_alpha"].min())
        if len(baseline_report)
        else math.inf
    )
    report["primary_metric_improvement_vs_best_baseline"] = np.where(
        baseline_best > 1e-12,
        report["mean_adjusted_oos_sharpe"] / baseline_best - 1.0,
        np.nan,
    )
    report["materially_lower_drawdown_turnover_capacity_drag"] = (
        (report["mean_max_drawdown"] <= baseline_drawdown)
        & (report["mean_turnover_notional_to_equity"] <= baseline_turnover)
        & (report["mean_capacity_drag_fraction_of_gross_alpha"] <= baseline_capacity_drag)
    ).astype(int)
    report["model_comparison_pass"] = (
        (report["model_name"] == "incumbent_ml")
        & (
            (report["primary_metric_improvement_vs_best_baseline"] >= 0.10)
            | (report["materially_lower_drawdown_turnover_capacity_drag"] == 1)
        )
    ).astype(int)
    report["schema_version"] = SCHEMA_VERSION
    report["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
    report["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
    report["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
    report["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
    report["trial_scope_formal"] = TRIAL_SCOPE_FORMAL
    report["trial_count_formal"] = 108
    return report.sort_values("mean_adjusted_oos_sharpe", ascending=False).reset_index(drop=True)


# ============================================================
# REPORTING HELPERS
# ============================================================
def plot_equity_curve(equity_df: pd.DataFrame, output_path: Path, title: str) -> None:
    if len(equity_df) == 0:
        return
    plt.figure(figsize=(10, 5))
    plt.plot(pd.to_datetime(equity_df["timestamp_utc"]), equity_df["equity"])
    plt.title(title)
    plt.xlabel("Time")
    plt.ylabel("Equity")
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def log_fold_metrics_summary(metrics: Dict[str, Any]) -> None:
    def _is_missing(x: object) -> bool:
        if x is None:
            return True
        try:
            xf = float(cast(Any, x))
            return not np.isfinite(xf)
        except Exception:
            return False

    def _get(key: str) -> object:
        return metrics.get(key)

    def _fmt_int(key: str) -> str:
        v = _get(key)
        if v is None:
            return "n/a"
        try:
            return f"{int(cast(Any, v))}"
        except Exception:
            return "n/a"

    def _fmt_float(key: str, decimals: int = 3) -> str:
        v = _get(key)
        if _is_missing(v):
            return "n/a"
        try:
            return f"{float(cast(Any, v)):.{decimals}f}"
        except Exception:
            return "n/a"

    def _fmt_pct(key: str, decimals: int = 1) -> str:
        v = _get(key)
        if _is_missing(v):
            return "n/a"
        try:
            return f"{float(cast(Any, v)) * 100:.{decimals}f}%"
        except Exception:
            return "n/a"

    def _fmt_money(key: str) -> str:
        v = _get(key)
        if _is_missing(v):
            return "n/a"
        try:
            return f"{float(cast(Any, v)):,.2f}"
        except Exception:
            return "n/a"

    def _fmt_pf(key: str = "profit_factor") -> str:
        v = _get(key)
        if _is_missing(v):
            return "n/a"
        try:
            xf = float(cast(Any, v))
            if xf == float("inf"):
                return "inf"
            return f"{xf:.2f}"
        except Exception:
            return "n/a"

    fold = str(_get("fold") or "n/a")
    max_concurrent = _fmt_int("max_concurrent")

    block = (
        "==================================================\n"
        f"Fold Summary | {fold} | max_concurrent={max_concurrent}\n"
        "--------------------------------------------------\n"
        "Thresholds: "
        f"p_min={_fmt_float('p_min', 2)}, "
        f"theta_ev={_fmt_float('theta_ev', 2)}, "
        f"theta_rel={_fmt_float('theta_rel', 2)}, "
        f"threshold_score={_fmt_float('threshold_score', 2)}\n"
        "Rows: "
        f"train={_fmt_int('train_rows')}, "
        f"test={_fmt_int('test_rows')}, "
        f"threshold_holdout={_fmt_int('threshold_holdout_rows')}\n"
        "Class balance: "
        f"train_pos_rate={_fmt_pct('train_pos_rate', 2)}, "
        f"test_pos_rate={_fmt_pct('test_pos_rate', 2)}, "
        f"threshold_holdout_pos_rate={_fmt_pct('threshold_holdout_pos_rate', 2)}\n"
        "Classification:\n"
        f"  train_roc_auc={_fmt_float('train_roc_auc', 3)}, test_roc_auc={_fmt_float('test_roc_auc', 3)}, "
        f"train_pr_auc={_fmt_float('train_pr_auc', 3)}, test_pr_auc={_fmt_float('test_pr_auc', 3)}\n"
        f"  train_log_loss={_fmt_float('train_log_loss', 4)}, test_log_loss={_fmt_float('test_log_loss', 4)}, "
        f"train_brier={_fmt_float('train_brier', 4)}, test_brier={_fmt_float('test_brier', 4)}\n"
        f"  benchmark_log_loss={_fmt_float('benchmark_log_loss', 4)}, benchmark_brier={_fmt_float('benchmark_brier', 4)}, "
        f"benchmark_roc_auc={_fmt_float('benchmark_roc_auc', 3)}, benchmark_pr_auc={_fmt_float('benchmark_pr_auc', 3)}\n"
        f"  threshold_holdout_log_loss={_fmt_float('threshold_holdout_log_loss', 4)}, threshold_holdout_brier={_fmt_float('threshold_holdout_brier', 4)}, "
        f"threshold_holdout_roc_auc={_fmt_float('threshold_holdout_roc_auc', 3)}, threshold_holdout_pr_auc={_fmt_float('threshold_holdout_pr_auc', 3)}\n"
        "Portfolio:\n"
        f"  n_trades={_fmt_int('n_trades')}, total_return={_fmt_pct('total_return', 2)}, cagr={_fmt_pct('cagr', 2)}, "
        f"mdd={_fmt_pct('mdd', 2)}, calmar={_fmt_float('calmar', 2)}\n"
        f"  profit_factor={_fmt_pf('profit_factor')}, win_rate={_fmt_pct('win_rate', 1)}, expectancy_r={_fmt_float('expectancy_r', 3)}, sharpe={_fmt_float('sharpe', 2)}\n"
        f"  avg_hold_hours={_fmt_float('avg_hold_hours', 2)}, ending_equity={_fmt_money('ending_equity')}, churn={_fmt_pct('churn', 2)}\n"
        f"  replacement_exits={_fmt_int('replacement_exits')}, total_exits={_fmt_int('total_exits')}, fold_selected={_fmt_int('fold_selected')}\n"
        f"  wrc_status={str(_get('wrc_status') or 'n/a')}, wrc_pvalue={_fmt_float('wrc_pvalue', 4)}, daily_calmar={_fmt_float('daily_calmar', 2)}, adjusted_sharpe_daily={_fmt_float('adjusted_sharpe_daily', 2)}\n"
        f"  spearman_ic_binary={_fmt_float('spearman_ic_binary', 3)}, spearman_ic_r_multiple={_fmt_float('spearman_ic_r_multiple', 3)}\n"
        "=================================================="
    )
    logging.info("%s", block)


def write_markdown_report(
    report_path: Path,
    output_root: Path,
    config: PipelineConfig,
    verification: Dict[str, object],
    feature_list: Sequence[str],
    fold_metrics: pd.DataFrame,
    overall_summary: Mapping[str, Any],
    feature_importance: pd.DataFrame,
) -> Path:
    lines: List[str] = []
    lines.append("# Final Swing Pipeline Report")
    lines.append("")
    lines.append("## 1. Scope")
    lines.append("")
    lines.append("This report summarizes the completed walk-forward, purged/embargoed, probability-calibrated swing pipeline.")
    lines.append("Outer folds use an expanding window (train window grows each fold).")
    lines.append("")
    lines.append("## 2. Input Panel Checks")
    lines.append("")
    lines.append(f"- **implementation_status**: {overall_summary.get('implementation_status')}")
    lines.append(f"- **verification_stage_reached**: {overall_summary.get('verification_stage_reached')}")
    for k, v in verification.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## 3. Locked Parameters")
    lines.append("")
    for k, v in asdict(config).items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## 4. Feature Set")
    lines.append("")
    lines.append(f"Total features used: **{len(feature_list)}**")
    lines.append("")
    for feat in feature_list:
        lines.append(f"- `{feat}`")
    lines.append("")
    lines.append("## 5. Fold-by-Fold Results")
    lines.append("")
    lines.append("(train_* metrics are in-sample / development diagnostics only; threshold_holdout_* and test_* are validation-grade.)")
    lines.append("")
    if len(fold_metrics):
        try:
            lines.append(fold_metrics.to_markdown(index=False))
        except Exception:
            lines.append(fold_metrics.to_string())
    else:
        lines.append("No fold metrics were generated.")
    lines.append("")
    lines.append("## 6. Overall Summary")
    lines.append("")
    for k, v in overall_summary.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Capacity")
    lines.append("")
    lines.append("- Max concurrent holdings is a cap of **8**, not a target occupancy.")
    lines.append("- Hard-gate robustness statistics are based on stitched calendar-day daily returns with idle selected-policy days recorded as zero returns.")
    lines.append("")
    lines.append("## Correction Flags")
    lines.append("")
    lines.append(f"- `threshold_search_corrected`: {overall_summary.get('threshold_search_corrected')}")
    lines.append(f"- `full_pipeline_corrected`: {overall_summary.get('full_pipeline_corrected')}")
    lines.append("")
    lines.append("## Trial Definition")
    lines.append("")
    lines.append(f"- `trial_scope_formal`: {overall_summary.get('trial_scope_formal')}")
    lines.append(f"- `trial_count_formal`: {overall_summary.get('trial_count_formal')}")
    lines.append(f"- `white_rc_pass_rate`: {overall_summary.get('white_rc_pass_rate')}")
    lines.append(f"- `deflated_sharpe_daily`: {overall_summary.get('deflated_sharpe_daily')}")
    lines.append(f"- `deflated_sharpe_probability`: {overall_summary.get('deflated_sharpe_probability')}")
    lines.append("")
    lines.append("## Ranking Map Guardrails")
    lines.append("")
    lines.append(f"- `ranking_map_guardrails_pass`: {overall_summary.get('ranking_map_guardrails_pass')}")
    lines.append(f"- `ranking_map_guardrail_failure_reasons`: {overall_summary.get('ranking_map_guardrail_failure_reasons')}")
    lines.append(
        f"- `ranking_map_max_fallback_usage_fraction_allowed`: {overall_summary.get('ranking_map_max_fallback_usage_fraction_allowed')}"
    )
    lines.append(
        f"- `ranking_map_min_adjacent_fold_spearman_allowed`: {overall_summary.get('ranking_map_min_adjacent_fold_spearman_allowed')}"
    )
    lines.append("")
    lines.append("## Promotion Decision")
    lines.append("")
    lines.append(f"- `robustness_pass`: {overall_summary.get('robustness_pass')}")
    lines.append(f"- `portfolio_policy_pass`: {overall_summary.get('portfolio_policy_pass')}")
    lines.append(f"- `evidence_hierarchy_pass`: {overall_summary.get('evidence_hierarchy_pass')}")
    lines.append(f"- `promotion_pass`: {overall_summary.get('promotion_pass')}")
    lines.append(f"- `robustness_reason`: {overall_summary.get('robustness_reason')}")
    lines.append(f"- `portfolio_policy_reason`: {overall_summary.get('portfolio_policy_reason')}")
    lines.append(f"- `evidence_hierarchy_reason`: {overall_summary.get('evidence_hierarchy_reason')}")
    lines.append(f"- `scorecard_label`: {overall_summary.get('scorecard_label')}")
    lines.append(f"- `scorecard_archetype`: {overall_summary.get('scorecard_archetype')}")
    lines.append(f"- `research_viable`: {overall_summary.get('research_viable')}")
    lines.append(f"- `live_pilot_viable`: {overall_summary.get('live_pilot_viable')}")
    lines.append(f"- `allocation_ready`: {overall_summary.get('allocation_ready')}")
    lines.append(f"- `feature_validation_pass`: {overall_summary.get('feature_validation_pass')}")
    lines.append(f"- `model_comparison_pass`: {overall_summary.get('model_comparison_pass')}")
    lines.append("")
    lines.append("## Top Feature Importances")
    lines.append("")
    if len(feature_importance):
        try:
            lines.append(feature_importance.head(25).to_markdown(index=False))
        except Exception:
            lines.append(feature_importance.head(25).to_string())
    else:
        lines.append("No feature importances available.")
    lines.append("")
    lines.append("## Output Directory")
    lines.append("")
    lines.append(f"All CSV / JSON / chart outputs were written to `{output_root}`.")
    lines.append("")
    atomic_write_text(report_path, "\n".join(lines), encoding="utf-8")
    return report_path


# ============================================================
# BASELINE GATING (for Optuna)
# ============================================================
def baseline_passed(fold_metrics_df: pd.DataFrame) -> bool:
    """True if a majority of folds beat the base-rate benchmark on log_loss and brier. Use before enabling Optuna.
    Uses one row per fold; verifies classification metrics are consistent across max_concurrent rows within each fold."""
    if len(fold_metrics_df) == 0:
        return False
    required_cols = {"test_log_loss", "test_brier", "benchmark_log_loss", "benchmark_brier"}
    if not required_cols.issubset(fold_metrics_df.columns):
        return False
    # One row per fold: verify consistency across max_concurrent rows, then take first or aggregate
    per_fold: List[Dict[str, float]] = []
    for fold_name, grp in fold_metrics_df.groupby("fold", sort=True):
        cols = ["test_log_loss", "test_brier", "benchmark_log_loss", "benchmark_brier"]
        if grp[cols].nunique().gt(1).any():
            logging.warning(
                "baseline_passed: fold %s has inconsistent classification metrics across max_concurrent rows; using mean",
                fold_name,
            )
            row = grp[cols].mean().to_dict()
        else:
            row = grp[cols].iloc[0].to_dict()
        per_fold.append(row)
    if not per_fold:
        return False
    one_per_fold = pd.DataFrame(per_fold)
    logloss_pass = (one_per_fold["test_log_loss"] < one_per_fold["benchmark_log_loss"]).mean()
    brier_pass = (one_per_fold["test_brier"] < one_per_fold["benchmark_brier"]).mean()
    return (logloss_pass >= 0.60) and (brier_pass >= 0.60)


def resolve_seed_list(config: PipelineConfig) -> List[int]:
    if config.seed_mode == "research":
        seeds = list(config.seed_list_research)
    elif config.seed_mode == "final":
        seeds = list(config.seed_list_final)
    else:
        seeds = [config.random_seed]
    # Preserve order while removing duplicates.
    ordered_unique = list(dict.fromkeys(int(s) for s in seeds))
    if config.random_seed not in ordered_unique:
        ordered_unique.insert(0, int(config.random_seed))
    return ordered_unique


def evaluate_seed_robustness(
    base_config: PipelineConfig,
    seed: int,
    model_df: pd.DataFrame,
    folds: Sequence[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]],
    features: Sequence[str],
    max_concurrent: int,
) -> Dict[str, Any]:
    """Evaluate one seed end-to-end on the shortlisted strategy policy (best max_concurrent)."""
    if seed == base_config.random_seed:
        raise RuntimeError("evaluate_seed_robustness should not be called for the primary seed.")
    seed_config = PipelineConfig(**{**asdict(base_config), "random_seed": int(seed), "resume": False, "seed_mode": "single"})
    seed_trades: List[pd.DataFrame] = []
    seed_equity: List[pd.DataFrame] = []
    seed_policy_daily_rows: List[Dict[str, Any]] = []
    completed_folds = 0
    for fold_num, (_, train_end, test_start, test_end) in enumerate(folds, start=1):
        fold_name = f"fold_{fold_num:02d}"
        train_df = model_df[model_df["timestamp_utc"] < train_end].copy()
        test_df = model_df[(model_df["timestamp_utc"] >= test_start) & (model_df["timestamp_utc"] < test_end)].copy()
        if len(train_df) == 0 or len(test_df) == 0:
            continue
        train_df = purge_outer_train_boundary(train_df, test_start)
        if len(train_df) == 0:
            continue
        max_train_ts = train_df["timestamp_utc"].max()
        threshold_holdout_start = max_train_ts - pd.DateOffset(months=seed_config.threshold_holdout_months)
        if threshold_holdout_start <= train_df["timestamp_utc"].min():
            continue
        threshold_holdout_df = train_df[train_df["timestamp_utc"] >= threshold_holdout_start].copy()
        threshold_fit_df = train_df[train_df["timestamp_utc"] < threshold_holdout_start].copy()
        threshold_fit_df = purge_outer_train_boundary(threshold_fit_df, threshold_holdout_start)
        if (
            len(threshold_holdout_df) < MIN_THRESHOLD_HOLDOUT_ROWS
            or len(threshold_holdout_df["long_win"].unique()) < 2
            or len(threshold_fit_df["long_win"].unique()) < 2
            or threshold_fit_df["timestamp_utc"].nunique() < seed_config.inner_folds
        ):
            continue
        _, threshold_holdout_scored, _, _, _ = fit_and_score_prediction_frame(
            threshold_fit_df,
            threshold_holdout_df,
            features,
            seed_config,
            f"{fold_name}_seed_{seed}",
        )
        if len(train_df["long_win"].unique()) < 2:
            continue
        _, test_scored, _, _, _, _ = fit_outer_fold(
            train_df,
            test_df,
            features,
            seed_config,
            f"{fold_name}_seed_{seed}",
        )
        thresholds, _, wrc_summary = choose_thresholds(threshold_holdout_scored, seed_config, f"{fold_name}_seed_{seed}", max_concurrent)
        fold_selected = int(wrc_summary.get("wrc_pass", 0) == 1)
        fold_skip_reason = "" if fold_selected else str(wrc_summary.get("wrc_status", "wrc_fail"))
        trades, equity, _ = simulate_book(
            test_scored,
            config=seed_config,
            max_concurrent=max_concurrent,
            p_min=thresholds["p_min"],
            theta_ev=thresholds["theta_ev"],
            theta_rel=thresholds["theta_rel"],
            fold_name=f"{fold_name}_seed_{seed}_slots_{max_concurrent}",
        )
        policy_daily = build_daily_equity_frame(
            equity if fold_selected else pd.DataFrame(),
            session_dates_from_frame(test_df),
            seed_config.starting_capital,
            max_concurrent,
        )
        if len(policy_daily):
            policy_daily["fold"] = fold_name
            policy_daily["max_concurrent"] = int(max_concurrent)
            policy_daily["fold_selected"] = int(fold_selected)
            policy_daily["fold_skip_reason"] = fold_skip_reason
            seed_policy_daily_rows.extend(policy_daily.to_dict("records"))
        if len(trades) and fold_selected:
            trades = trades.copy()
            trades["fold"] = fold_name
            trades["max_concurrent"] = max_concurrent
            seed_trades.append(trades)
        if len(equity) and fold_selected:
            equity = equity.copy()
            equity["fold"] = fold_name
            equity["max_concurrent"] = max_concurrent
            seed_equity.append(equity)
        completed_folds += 1
    if completed_folds == 0:
        raise RuntimeError(f"Seed robustness failed for seed={seed}: no valid folds completed.")
    trades_df = pd.concat(seed_trades, ignore_index=True) if seed_trades else pd.DataFrame()
    equity_df = pd.concat(seed_equity, ignore_index=True) if seed_equity else pd.DataFrame()
    equity_best = chain_equity_curves(equity_df, max_concurrent, seed_config.starting_capital)
    metrics = compute_metrics(trades_df, equity_best, seed_config)
    _, stitched_summary = summarize_stitched_policy_daily(
        pd.DataFrame(seed_policy_daily_rows),
        starting_capital=seed_config.starting_capital,
        trial_count=threshold_policy_trial_count(seed_config),
    )
    metrics.update(stitched_summary)
    return {
        "seed": int(seed),
        "n_folds": int(completed_folds),
        "n_selected_folds": int(pd.DataFrame(seed_policy_daily_rows)["fold_selected"].sum()) if seed_policy_daily_rows else 0,
        "n_trades": float(metrics.get("n_trades", np.nan)),
        "profit_factor": float(metrics.get("profit_factor", np.nan)),
        "calmar": float(metrics.get("stitched_daily_calmar", metrics.get("calmar", np.nan))),
        "expectancy_r": float(metrics.get("expectancy_r", np.nan)),
        "cagr": float(metrics.get("stitched_daily_cagr", metrics.get("cagr", np.nan))),
        "mdd": float(metrics.get("stitched_daily_mdd", metrics.get("mdd", np.nan))),
        "sharpe": float(metrics.get("sharpe", np.nan)),
        "adjusted_sharpe_daily": float(metrics.get("adjusted_sharpe_daily", np.nan)),
        "deflated_sharpe_daily": float(metrics.get("deflated_sharpe_daily", np.nan)),
        "promotion_pass": bool(
            np.isfinite(float(metrics.get("deflated_sharpe_daily", np.nan)))
            and float(metrics.get("deflated_sharpe_daily", np.nan)) > 0
        ),
    }


# Canonical base for all pipeline artifacts. All outputs and inputs resolve under this path.
# Override via env PIPELINE_BASE_PATH if the repo is cloned elsewhere.
CANONICAL_BASE = Path(os.environ.get("PIPELINE_BASE_PATH", "E:/stock_csvs_AI-Perspective/NEW"))


# ============================================================
# MAIN DRIVER
# ============================================================
def _resolve_project_path(path_str: str, force_project_drive: bool = False) -> Path:
    """Resolve a path so all artifacts stay on E:\\stock_csvs_AI-Perspective.
    Uses CANONICAL_BASE (E:\\stock_csvs_AI-Perspective\\NEW) as the project root.
    If force_project_drive is True, absolute paths on other drives are rewritten under CANONICAL_BASE."""
    p = Path(path_str)
    base = CANONICAL_BASE.resolve()
    if p.is_absolute():
        if force_project_drive:
            path_drive = getattr(p, "drive", "") or ""
            base_drive = getattr(base, "drive", "") or ""
            if path_drive and base_drive and path_drive.upper() != base_drive.upper():
                return (base / p.name).resolve()
        else:
            return p
    return (base / p).resolve()


def load_resume_collections(
    paths: OutputPaths,
    completed_fold_names: Sequence[str],
) -> Dict[str, Any]:
    loaded: Dict[str, Any] = {
        "all_fold_metrics": [],
        "all_trades": [],
        "all_equity": [],
        "all_feature_importance": [],
        "all_inner_feature_importance": [],
        "all_permutation_rows": [],
        "all_subset_search_rows": [],
        "all_selected_feature_rows": [],
        "all_rejected_feature_rows": [],
        "all_regime_rows": [],
        "all_fold_ic": [],
        "all_thresholds": [],
        "all_threshold_candidate_rows": [],
        "all_policy_daily_rows": [],
        "all_feature_validation_rows": [],
        "all_feature_validation_daily_rows": [],
        "all_model_comparison_rows": [],
        "all_position_ranking_rows": [],
        "verification": None,
    }
    if not completed_fold_names:
        return loaded
    record_specs = [
        ("all_fold_metrics", paths.metrics_dir / "fold_metrics.csv"),
        ("all_permutation_rows", paths.features_dir / "permutation_importance.csv"),
        ("all_subset_search_rows", paths.features_dir / "subset_search_summary.csv"),
        ("all_selected_feature_rows", paths.features_dir / "selected_features_by_fold.csv"),
        ("all_rejected_feature_rows", paths.features_dir / "rejected_features_by_fold.csv"),
        ("all_regime_rows", paths.features_dir / "regime_specific_importance.csv"),
        ("all_fold_ic", paths.metrics_dir / "fold_ic_summary.csv"),
        ("all_thresholds", paths.metrics_dir / "selected_thresholds.csv"),
        ("all_threshold_candidate_rows", paths.metrics_dir / "threshold_candidate_diagnostics.csv"),
        ("all_policy_daily_rows", paths.metrics_dir / "policy_daily_returns.csv"),
        ("all_feature_validation_rows", paths.features_dir / "feature_validation_rows.csv"),
        ("all_feature_validation_daily_rows", paths.features_dir / "feature_validation_ic_daily_rows.csv"),
        ("all_model_comparison_rows", paths.strategies_dir / "model_comparison_report_rows.csv"),
        ("all_position_ranking_rows", paths.strategies_dir / "position_ranking_audit.csv"),
    ]
    frame_specs = [
        ("all_trades", paths.metrics_dir / "trade_blotter.csv"),
        ("all_equity", paths.metrics_dir / "equity_curves.csv"),
        ("all_feature_importance", paths.features_dir / "feature_importances_by_fold.csv"),
        ("all_inner_feature_importance", paths.features_dir / "inner_feature_importances_by_fold.csv"),
    ]
    for key, artifact_path in record_specs:
        if artifact_path.exists():
            loaded[key] = pd.read_csv(artifact_path).to_dict("records")
    for key, artifact_path in frame_specs:
        if artifact_path.exists():
            loaded[key] = [pd.read_csv(artifact_path)]
    ver_path = paths.state_dir / "verification.json"
    if ver_path.exists():
        loaded["verification"] = json.loads(ver_path.read_text(encoding="utf-8"))
    return loaded


def _install_sigint_handler() -> None:
    """Install SIGINT handler for graceful exit. Resume state is saved after each fold."""
    def _handler(signum: int, frame: object) -> None:
        logging.info("Interrupted by user (SIGINT). Resume with --resume to continue from last completed fold.")
        raise SystemExit(130)
    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):
        pass  # Not in main thread or signal not available


def _restore_previous_ranking_map_profiles(
    all_fold_metrics: Sequence[Mapping[str, Any]],
    completed_fold_names: Sequence[str],
) -> Tuple[Optional[List[float]], Optional[List[float]]]:
    if not all_fold_metrics or not completed_fold_names:
        return None, None
    last_fold_name = str(completed_fold_names[-1])
    for row in reversed(all_fold_metrics):
        if str(row.get("fold", "")) != last_fold_name:
            continue
        threshold_rates = _deserialize_bucket_positive_rates(
            row.get("ranking_map_bucket_positive_rates_threshold_holdout")
        )
        test_rates = _deserialize_bucket_positive_rates(
            row.get("ranking_map_bucket_positive_rates_test")
        )
        return threshold_rates, test_rates
    return None, None


def _ranking_map_artifact_fields(meta: Mapping[str, Any], *, suffix: str) -> Dict[str, Any]:
    return {
        f"ranking_map_bucket_positive_rates_{suffix}": meta.get("ranking_map_bucket_positive_rates", "[]"),
        f"ranking_map_fallback_usage_fraction_{suffix}": meta.get("ranking_map_fallback_usage_fraction", np.nan),
        f"ranking_map_adjacent_fold_spearman_{suffix}": meta.get("ranking_map_adjacent_fold_spearman", np.nan),
        f"ranking_map_adjacent_fold_spearman_evaluable_{suffix}": meta.get(
            "ranking_map_adjacent_fold_spearman_evaluable",
            False,
        ),
        f"ranking_map_guardrails_pass_{suffix}": meta.get("ranking_map_guardrails_pass", False),
        f"ranking_map_guardrail_failure_reasons_{suffix}": meta.get("ranking_map_guardrail_failure_reasons", ""),
    }


def summarize_ranking_map_guardrails(
    fold_metrics: pd.DataFrame,
    config: PipelineConfig,
) -> Dict[str, Any]:
    if fold_metrics.empty:
        return {
            "ranking_map_guardrails_pass": False,
            "ranking_map_guardrail_failure_reasons": "no_fold_metrics",
            "ranking_map_guardrail_failed_fold_count": 0,
            "ranking_map_guardrail_evaluable_fold_count_threshold_holdout": 0,
            "ranking_map_guardrail_evaluable_fold_count_test": 0,
            "ranking_map_max_fallback_usage_fraction_allowed": float(config.empirical_prob_map_max_fallback_usage_fraction),
            "ranking_map_min_adjacent_fold_spearman_allowed": float(config.empirical_prob_map_min_adjacent_fold_spearman),
            "ranking_map_fallback_usage_fraction_observed_max_threshold_holdout": np.nan,
            "ranking_map_fallback_usage_fraction_observed_max_test": np.nan,
            "ranking_map_adjacent_fold_spearman_observed_min_threshold_holdout": np.nan,
            "ranking_map_adjacent_fold_spearman_observed_min_test": np.nan,
        }

    def _to_bool_series(column: str) -> pd.Series:
        if column not in fold_metrics.columns:
            return pd.Series(False, index=fold_metrics.index, dtype=bool)
        values = fold_metrics[column]
        if values.dtype == bool:
            return values.fillna(False)
        return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})

    def _to_numeric_series(column: str) -> pd.Series:
        if column not in fold_metrics.columns:
            return pd.Series(np.nan, index=fold_metrics.index, dtype=float)
        return pd.to_numeric(fold_metrics[column], errors="coerce")

    def _finite_min(series: pd.Series) -> float:
        valid = series[np.isfinite(series.astype(float))]
        return float(valid.min()) if len(valid) else np.nan

    failure_reasons: List[str] = []
    for column in (
        "ranking_map_guardrail_failure_reasons_threshold_holdout",
        "ranking_map_guardrail_failure_reasons_test",
    ):
        if column not in fold_metrics.columns:
            continue
        for raw in fold_metrics[column].dropna().astype(str):
            text = raw.strip()
            if not text or text == "ok":
                continue
            for item in text.split(";"):
                candidate = item.strip()
                if candidate and candidate not in failure_reasons:
                    failure_reasons.append(candidate)

    threshold_evaluable = _to_bool_series("ranking_map_adjacent_fold_spearman_evaluable_threshold_holdout")
    test_evaluable = _to_bool_series("ranking_map_adjacent_fold_spearman_evaluable_test")
    threshold_pass = _to_bool_series("ranking_map_guardrails_pass_threshold_holdout")
    test_pass = _to_bool_series("ranking_map_guardrails_pass_test")
    failed_rows = (~threshold_pass) | (~test_pass)

    return {
        "ranking_map_guardrails_pass": bool((~failed_rows).all()),
        "ranking_map_guardrail_failure_reasons": "ok" if not failure_reasons else ";".join(failure_reasons),
        "ranking_map_guardrail_failed_fold_count": int(failed_rows.sum()),
        "ranking_map_guardrail_evaluable_fold_count_threshold_holdout": int(threshold_evaluable.sum()),
        "ranking_map_guardrail_evaluable_fold_count_test": int(test_evaluable.sum()),
        "ranking_map_max_fallback_usage_fraction_allowed": float(config.empirical_prob_map_max_fallback_usage_fraction),
        "ranking_map_min_adjacent_fold_spearman_allowed": float(config.empirical_prob_map_min_adjacent_fold_spearman),
        "ranking_map_fallback_usage_fraction_observed_max_threshold_holdout": float(
            _to_numeric_series("ranking_map_fallback_usage_fraction_threshold_holdout").max()
        ),
        "ranking_map_fallback_usage_fraction_observed_max_test": float(
            _to_numeric_series("ranking_map_fallback_usage_fraction_test").max()
        ),
        "ranking_map_adjacent_fold_spearman_observed_min_threshold_holdout": _finite_min(
            _to_numeric_series("ranking_map_adjacent_fold_spearman_threshold_holdout").where(threshold_evaluable, np.nan)
        ),
        "ranking_map_adjacent_fold_spearman_observed_min_test": _finite_min(
            _to_numeric_series("ranking_map_adjacent_fold_spearman_test").where(test_evaluable, np.nan)
        ),
    }


def _optuna_artifact_fields(summary: Mapping[str, Any], *, prefix: str) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {
        f"{prefix}_optuna_wall_clock_cap_seconds": int(OPTUNA_MAX_WALL_CLOCK_SECONDS),
    }
    for model_name in ("RF", "ET", "XGB"):
        model_summary = summary.get(model_name, {}) if isinstance(summary, Mapping) else {}
        key_prefix = f"{prefix}_optuna_{model_name.lower()}"
        flattened[f"{key_prefix}_elapsed_seconds"] = (
            float(model_summary.get("elapsed_seconds", np.nan)) if isinstance(model_summary, Mapping) else np.nan
        )
        flattened[f"{key_prefix}_completed_trials"] = (
            int(model_summary.get("completed_trials", 0)) if isinstance(model_summary, Mapping) else 0
        )
        flattened[f"{key_prefix}_requested_trials"] = (
            int(model_summary.get("requested_trials", 0)) if isinstance(model_summary, Mapping) else 0
        )
        flattened[f"{key_prefix}_stopped_for_wall_clock"] = (
            bool(model_summary.get("stopped_for_wall_clock", False)) if isinstance(model_summary, Mapping) else False
        )
    return flattened


def run_pipeline(config: PipelineConfig) -> Dict[str, object]:
    _install_sigint_handler()
    # Resolve paths relative to project root so files are saved to the project drive (e.g. E:)
    output_dir = _resolve_project_path(config.output_dir, force_project_drive=True)
    config.output_dir = str(output_dir)
    input_path = _resolve_project_path(config.input_panel_csv)
    config.input_panel_csv = str(input_path)
    if config.deterministic_mode:
        config.n_jobs_tree_models = 1
        config.n_jobs_xgb = 1
        config.seed_mode = "single"
    paths = build_output_paths(output_dir)
    if not config.resume:
        invalidate_stale_reports(paths)
    setup_logging(paths, resume=config.resume)
    requested_status = str(config.implementation_status)
    requested_stage = str(config.verification_stage_reached)
    normalized_status, normalized_stage = normalize_implementation_claim(
        requested_status,
        requested_stage,
        deterministic_mode=bool(config.deterministic_mode),
    )
    if (normalized_status, normalized_stage) != (requested_status, requested_stage):
        logging.info(
            "Normalized implementation claim from status=%s stage=%s to status=%s stage=%s",
            requested_status,
            requested_stage,
            normalized_status,
            normalized_stage,
        )
    config.implementation_status = normalized_status
    config.verification_stage_reached = normalized_stage
    cost_model_ok, missing_cost_fields, cost_model_snapshot = validate_cost_model(config)
    if not cost_model_ok:
        raise RuntimeError(f"Invalid cost model schema; missing required fields: {missing_cost_fields}")
    code_fingerprint = build_code_fingerprint()
    input_data_hash = build_input_data_hash(input_path)
    input_build_metadata = load_input_build_metadata(input_path)
    require_input_build_metadata(input_path, input_build_metadata)
    config_hash = build_config_hash(config)
    config_snapshot_payload: Dict[str, Any] = {
        **asdict(config),
        "schema_version": SCHEMA_VERSION,
        "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
        "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
        "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
        "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
        "trial_scope_formal": TRIAL_SCOPE_FORMAL,
        "trial_count_formal": int(threshold_policy_trial_count(config)),
        "scorecard_label": SCORECARD_LABEL,
        "scorecard_archetype": SCORECARD_ARCHETYPE,
        "code_fingerprint": code_fingerprint,
        "input_data_hash": input_data_hash,
        "config_hash": config_hash,
        "effective_cost_model": cost_model_snapshot,
        **input_build_metadata,
    }
    atomic_write_json(paths.state_dir / "config_snapshot.json", config_snapshot_payload)
    if config.use_optuna_tuning and config.require_baseline_pass_for_tuning:
        fm_path = paths.metrics_dir / "fold_metrics.csv"
        if not fm_path.exists():
            raise RuntimeError(
                "Optuna tuning requested, but no baseline fold_metrics.csv exists. "
                "Run the untuned baseline first."
            )
        baseline_df = pd.read_csv(fm_path)
        if not baseline_passed(baseline_df):
            raise RuntimeError(
                "Optuna tuning requested, but baseline_passed() is False. "
                "Do not tune until the untuned baseline beats the benchmark."
            )
        logging.info("Optuna tuning enabled: baseline check passed (fold_metrics.csv exists and baseline_passed()).")
    resume_path = paths.state_dir / "resume_state.json"
    pre_fold_shortcut = False
    model_df: Optional[pd.DataFrame] = None
    features: List[str] = []
    folds: List[Tuple[object, object, object, object]] = []
    n_folds = 0
    feature_registry_df: Optional[pd.DataFrame] = None
    verification: Dict[str, Any] = {
        "lightgbm_available": LIGHTGBM_AVAILABLE,
        "cost_model_valid": bool(cost_model_ok),
        "missing_cost_model_fields": list(missing_cost_fields),
        "effective_cost_model": cost_model_snapshot,
        "schema_version": SCHEMA_VERSION,
        "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
        "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
        "code_fingerprint": code_fingerprint,
        "input_data_hash": input_data_hash,
        "config_hash": config_hash,
        **input_build_metadata,
    }
    all_trades: List[pd.DataFrame] = []
    all_equity: List[pd.DataFrame] = []
    all_fold_metrics: List[Dict[str, Any]] = []
    all_fold_ic: List[Dict[str, Any]] = []
    all_feature_importance: List[pd.DataFrame] = []
    all_inner_feature_importance: List[pd.DataFrame] = []
    all_permutation_rows: List[Dict[str, Any]] = []
    all_subset_search_rows: List[Dict[str, Any]] = []
    all_selected_feature_rows: List[Dict[str, Any]] = []
    all_rejected_feature_rows: List[Dict[str, Any]] = []
    all_regime_rows: List[Dict[str, Any]] = []
    all_thresholds: List[Dict[str, object]] = []
    all_threshold_candidate_rows: List[Dict[str, Any]] = []
    all_policy_daily_rows: List[Dict[str, Any]] = []
    all_feature_validation_rows: List[Dict[str, Any]] = []
    all_feature_validation_daily_rows: List[Dict[str, Any]] = []
    all_model_comparison_rows: List[Dict[str, Any]] = []
    all_position_ranking_rows: List[Dict[str, Any]] = []
    previous_threshold_bucket_positive_rates: Optional[List[float]] = None
    previous_test_bucket_positive_rates: Optional[List[float]] = None
    completed_fold_names: List[str] = []
    resume_fingerprint = build_resume_fingerprint(config)
    if config.resume and resume_path.exists():
        model_path = paths.data_dir / "model_ready_dataset.csv"
        registry_path = paths.features_dir / "feature_registry.csv"
        if model_path.exists() and registry_path.exists():
            try:
                state = json.loads(resume_path.read_text(encoding="utf-8"))
                fingerprint_ok = state.get("resume_fingerprint") == resume_fingerprint
                if fingerprint_ok:
                    model_df = pd.read_csv(model_path)
                    for col in ("timestamp_utc", "event_end_time"):
                        if col in model_df.columns:
                            model_df[col] = pd.to_datetime(model_df[col], utc=True)
                    feature_registry_df = pd.read_csv(registry_path)
                    default_on = feature_registry_df["default_enabled"].astype(str).str.lower() == "true"
                    available = feature_registry_df["availability_status"] == "available"
                    features = [f for f in feature_registry_df.loc[default_on & available, "feature_name"].tolist() if f in model_df.columns]
                    if features:
                        folds = build_outer_folds(model_df, config)
                        n_folds = len(folds)
                        completed_fold_names = state.get("completed_fold_names", [])
                        logging.info("Resume: pre-fold shortcut — reusing model_ready_dataset and feature_registry (%s rows, %s folds done)", len(model_df), len(completed_fold_names))
                        loaded = load_resume_collections(paths, completed_fold_names)
                        all_fold_metrics = loaded["all_fold_metrics"]
                        all_trades = loaded["all_trades"]
                        all_equity = loaded["all_equity"]
                        all_feature_importance = loaded["all_feature_importance"]
                        all_inner_feature_importance = loaded["all_inner_feature_importance"]
                        all_permutation_rows = loaded["all_permutation_rows"]
                        all_subset_search_rows = loaded["all_subset_search_rows"]
                        all_selected_feature_rows = loaded["all_selected_feature_rows"]
                        all_rejected_feature_rows = loaded["all_rejected_feature_rows"]
                        all_regime_rows = loaded["all_regime_rows"]
                        all_fold_ic = loaded["all_fold_ic"]
                        all_thresholds = loaded["all_thresholds"]
                        all_threshold_candidate_rows = loaded["all_threshold_candidate_rows"]
                        all_policy_daily_rows = loaded["all_policy_daily_rows"]
                        all_feature_validation_rows = loaded["all_feature_validation_rows"]
                        all_feature_validation_daily_rows = loaded["all_feature_validation_daily_rows"]
                        all_model_comparison_rows = loaded["all_model_comparison_rows"]
                        all_position_ranking_rows = loaded["all_position_ranking_rows"]
                        (
                            previous_threshold_bucket_positive_rates,
                            previous_test_bucket_positive_rates,
                        ) = _restore_previous_ranking_map_profiles(all_fold_metrics, completed_fold_names)
                        if loaded.get("verification") is not None:
                            verification = loaded["verification"]
                        pre_fold_shortcut = True
            except Exception as e:
                logging.warning("Resume pre-fold shortcut failed: %s. Running full flow.", e)
    if not pre_fold_shortcut:
        logging.info("Loading panel from %s", config.input_panel_csv)
        panel = load_panel(config)
        panel_verification = verify_panel(panel)
        verification.update(panel_verification)
        verification["lightgbm_available"] = LIGHTGBM_AVAILABLE
        regularity = verify_panel_timestamp_regularity(panel)
        write_panel_regularity_outputs(output_dir, regularity)
        cov = regularity.get("coverage_summary", {})
        tickers_below_95_span = int(cov.get("tickers_below_95pct_span", 0) or 0)
        tickers_below_90_span = int(cov.get("tickers_below_90pct_span", 0) or 0)
        if tickers_below_95_span > 0 or tickers_below_90_span > 0:
            logging.warning(
                "Panel embargo assumption: %s tickers below 95%% span coverage (scattered gaps), %s below 90%%. "
                "Purged/embargo splits use global timestamps; per-ticker missing bars may weaken embargo. "
                "Late-start tickers (e.g. IPO) are excluded from this check. "
                "See 00_logs/panel_timestamp_regularity_by_ticker.csv for diagnostics.",
                tickers_below_95_span, tickers_below_90_span,
            )
        logging.info("Panel verification: %s", verification)
        try:
            logging.info("Building feature matrix (panel rows=%s, tickers=%s)...", len(panel), panel["ticker"].nunique())
            enriched, features = build_feature_matrix(panel, config)
            logging.info("Feature matrix built: %s rows, %s features", len(enriched), len(features))
        except Exception as e:
            logging.exception("build_feature_matrix failed: %s", e)
            raise
        # Build and persist a canonical feature registry for the implemented feature set.
        features_dir = paths.features_dir
        feature_registry_df = build_feature_registry(features)
        config_snapshot_payload["feature_set_version"] = build_feature_set_version(features)
        verification["feature_set_version"] = config_snapshot_payload["feature_set_version"]
        registry_path = features_dir / "feature_registry.csv"
        coverage_path = features_dir / "feature_registry_coverage_summary.csv"
        atomic_write_csv(feature_registry_df, registry_path)
        # Coverage summary: counts by family, type, and availability.
        total_named = int(len(feature_registry_df))
        total_active = int(
            feature_registry_df[
                feature_registry_df["default_enabled"] & (feature_registry_df["availability_status"] == "available")
            ].shape[0]
        )
        total_unavailable = int(feature_registry_df[feature_registry_df["availability_status"] != "available"].shape[0])
        cov_rows: List[Dict[str, object]] = []
        cov_rows.append({"metric": "total_named_features", "value": total_named})
        cov_rows.append({"metric": "total_active_features", "value": total_active})
        cov_rows.append({"metric": "total_unavailable_features", "value": total_unavailable})
        by_family = feature_registry_df.groupby("family")["feature_name"].count().reset_index(name="count")
        for _, row in by_family.iterrows():
            cov_rows.append(
                {
                    "metric": f"family_count::{row['family']}",
                    "value": int(row["count"]),
                }
            )
        by_type = feature_registry_df.groupby("regular_or_physics")["feature_name"].count().reset_index(name="count")
        for _, row in by_type.iterrows():
            cov_rows.append(
                {
                    "metric": f"type_count::{row['regular_or_physics']}",
                    "value": int(row["count"]),
                }
            )
        atomic_write_csv(pd.DataFrame(cov_rows), coverage_path)
        logging.info("Starting label_long_events on %s enriched rows...", len(enriched))
        label_start = time.perf_counter()
        labeled = label_long_events(enriched, config)
        logging.info("label_long_events complete: %s rows in %.2fs", len(labeled), time.perf_counter() - label_start)
        labeled_rows_before_session_filter = len(labeled)
        labeled = labeled[~labeled["is_incomplete_session"].astype(bool)].copy()
        logging.info(
            "Incomplete-session filter retained %s/%s labeled rows",
            len(labeled),
            labeled_rows_before_session_filter,
        )
        feature_columns = list(features)
        logging.info(
            "Computing missing_feature_fraction for %s rows across %s features...",
            len(labeled),
            len(feature_columns),
        )
        missing_fraction_start = time.perf_counter()
        if feature_columns:
            present_feature_counts = labeled[feature_columns].count(axis=1)
            labeled["missing_feature_fraction"] = 1.0 - (present_feature_counts / float(len(feature_columns)))
        else:
            labeled["missing_feature_fraction"] = np.nan
        logging.info("missing_feature_fraction computed in %.2fs", time.perf_counter() - missing_fraction_start)
        model_df = labeled[labeled["missing_feature_fraction"] <= config.max_missing_feature_fraction].copy()
        model_path = paths.data_dir / "model_ready_dataset.csv"
        logging.info("Writing model-ready dataset to %s (%s rows)", model_path, len(model_df))
        atomic_write_csv(model_df, model_path)
        logging.info("Model-ready dataset written to %s (%s rows)", model_path, len(model_df))
        folds = build_outer_folds(model_df, config)
        n_folds = len(folds)
        logging.info("Built %s outer folds", n_folds)
        if config.resume and resume_path.exists():
            try:
                state = json.loads(resume_path.read_text(encoding="utf-8"))
                fingerprint_ok = state.get("resume_fingerprint") == resume_fingerprint
                if fingerprint_ok:
                    completed_fold_names = state.get("completed_fold_names", [])
                    logging.info("Resume: found %s completed folds: %s", len(completed_fold_names), completed_fold_names)
                    loaded = load_resume_collections(paths, completed_fold_names)
                    all_fold_metrics = loaded["all_fold_metrics"]
                    all_trades = loaded["all_trades"]
                    all_equity = loaded["all_equity"]
                    all_feature_importance = loaded["all_feature_importance"]
                    all_inner_feature_importance = loaded["all_inner_feature_importance"]
                    all_permutation_rows = loaded["all_permutation_rows"]
                    all_subset_search_rows = loaded["all_subset_search_rows"]
                    all_selected_feature_rows = loaded["all_selected_feature_rows"]
                    all_rejected_feature_rows = loaded["all_rejected_feature_rows"]
                    all_regime_rows = loaded["all_regime_rows"]
                    all_fold_ic = loaded["all_fold_ic"]
                    all_thresholds = loaded["all_thresholds"]
                    all_threshold_candidate_rows = loaded["all_threshold_candidate_rows"]
                    all_policy_daily_rows = loaded["all_policy_daily_rows"]
                    all_feature_validation_rows = loaded["all_feature_validation_rows"]
                    all_feature_validation_daily_rows = loaded["all_feature_validation_daily_rows"]
                    all_model_comparison_rows = loaded["all_model_comparison_rows"]
                    all_position_ranking_rows = loaded["all_position_ranking_rows"]
                    (
                        previous_threshold_bucket_positive_rates,
                        previous_test_bucket_positive_rates,
                    ) = _restore_previous_ranking_map_profiles(all_fold_metrics, completed_fold_names)
                else:
                    logging.info("Resume state rejected: config changed (fingerprint mismatch). Starting fresh.")
            except Exception as e:
                logging.warning("Resume: failed to load state: %s", e)
    feature_family_map = feature_registry_df.set_index("feature_name")["family"].to_dict()
    for fold_num, (_, train_end, test_start, test_end) in enumerate(folds, start=1):
        fold_name = f"fold_{fold_num:02d}"
        if fold_name in completed_fold_names:
            logging.info("Resume: skipping already completed %s", fold_name)
            continue
        logging.info("[%s / %s] === %s | train<%s | test[%s .. %s) ===", fold_num, n_folds, fold_name, train_end, test_start, test_end)
        logging.info("test_start=%s (for chronology)", test_start)
        train_df = model_df[model_df["timestamp_utc"] < train_end].copy()
        test_df = model_df[(model_df["timestamp_utc"] >= test_start) & (model_df["timestamp_utc"] < test_end)].copy()
        if len(train_df) == 0 or len(test_df) == 0:
            logging.info("Skipping %s due to empty train/test split", fold_name)
            continue
        # FIX 1: Outer-boundary purge — remove train rows whose event_end_time extends into test (leakage)
        train_rows_before_purge = len(train_df)
        train_df = purge_outer_train_boundary(train_df, test_start)
        rows_removed = train_rows_before_purge - len(train_df)
        logging.info("Outer-boundary purge: train rows before=%s, after=%s, removed=%s", train_rows_before_purge, len(train_df), rows_removed)
        assert (train_df["event_end_time"] < test_start).all(), "No training row may have event_end_time >= test_start"
        if len(train_df) == 0:
            logging.info("Skipping %s: no train rows left after outer-boundary purge", fold_name)
            continue
        # Threshold holdout: calendar-month split of purged outer-train (FIX 2)
        max_train_ts = train_df["timestamp_utc"].max()
        threshold_holdout_start = max_train_ts - pd.DateOffset(months=config.threshold_holdout_months)
        logging.info("threshold_holdout_start=%s (for chronology)", threshold_holdout_start)
        if threshold_holdout_start <= train_df["timestamp_utc"].min():
            logging.info(
                "Skipping %s: threshold holdout degenerate (threshold_holdout_start <= purged train min). Do not add to completed_fold_names.",
                fold_name,
            )
            continue
        threshold_holdout_df = train_df[train_df["timestamp_utc"] >= threshold_holdout_start].copy()
        threshold_fit_df = train_df[train_df["timestamp_utc"] < threshold_holdout_start].copy()
        threshold_fit_rows_before = len(threshold_fit_df)
        threshold_fit_df = purge_outer_train_boundary(threshold_fit_df, threshold_holdout_start)
        threshold_fit_rows_after = len(threshold_fit_df)
        logging.info(
            "Threshold split: threshold_fit rows before purge=%s, after purge=%s; threshold_holdout rows=%s",
            threshold_fit_rows_before, threshold_fit_rows_after, len(threshold_holdout_df),
        )
        assert (threshold_fit_df["event_end_time"] < threshold_holdout_start).all() if len(threshold_fit_df) else True
        # Viability checks: skip fold with clear reason, do not add to completed_fold_names
        if len(threshold_holdout_df) < MIN_THRESHOLD_HOLDOUT_ROWS:
            logging.info(
                "Skipping %s: threshold_holdout_df has %s rows (min %s). Do not add to completed_fold_names.",
                fold_name, len(threshold_holdout_df), MIN_THRESHOLD_HOLDOUT_ROWS,
            )
            continue
        if len(threshold_holdout_df["long_win"].unique()) < 2:
            logging.info(
                "Skipping %s: threshold_holdout_df lacks both classes. Do not add to completed_fold_names.",
                fold_name,
            )
            continue
        if len(threshold_fit_df["long_win"].unique()) < 2:
            logging.info(
                "Skipping %s: threshold_fit_df lacks both classes. Do not add to completed_fold_names.",
                fold_name,
            )
            continue
        if threshold_fit_df["timestamp_utc"].nunique() < config.inner_folds:
            logging.info(
                "Skipping %s: threshold_fit_df has %s unique timestamps (need >= inner_folds=%s). Do not add to completed_fold_names.",
                fold_name, threshold_fit_df["timestamp_utc"].nunique(), config.inner_folds,
            )
            continue
        try:
            threshold_fit_scored, threshold_holdout_scored, _, _, threshold_empirical_meta = fit_and_score_prediction_frame(
                threshold_fit_df,
                threshold_holdout_df,
                features,
                config,
                fold_name,
                previous_bucket_positive_rates=previous_threshold_bucket_positive_rates,
            )
        except RuntimeError as e:
            msg = str(e)
            if "calibration holdout failed viability check" in msg:
                logging.info("Skipping %s: %s", fold_name, msg)
            else:
                logging.info(
                    "Skipping %s: fit_and_score_prediction_frame failed (%s). Do not add to completed_fold_names.",
                    fold_name, e,
                )
            continue
        # Threshold selection only on out-of-sample threshold holdout (never on train_scored)
        th_holdout_diag = classification_diagnostics(
            threshold_holdout_scored["long_win"], threshold_holdout_scored["p_cal"]
        )
        # Final purged outer-train: if lacks both classes, skip fold
        if len(train_df["long_win"].unique()) < 2:
            logging.info(
                "Skipping %s: full purged outer-train lacks both classes. Do not add to completed_fold_names.",
                fold_name,
            )
            continue
        try:
            train_scored, test_scored, inner_imp, full_imp, calib_stats, empirical_meta = fit_outer_fold(
                train_df,
                test_df,
                features,
                config,
                fold_name,
                previous_bucket_positive_rates=previous_test_bucket_positive_rates,
            )
        except RuntimeError as e:
            msg = str(e)
            if "calibration holdout failed viability check" in msg:
                logging.info("Skipping %s: %s", fold_name, msg)
            else:
                logging.info(
                    "Skipping %s: fit_outer_fold failed (%s). Do not add to completed_fold_names.",
                    fold_name, e,
                )
            continue
        current_threshold_bucket_positive_rates = _deserialize_bucket_positive_rates(
            threshold_empirical_meta.get("ranking_map_bucket_positive_rates")
        )
        current_test_bucket_positive_rates = _deserialize_bucket_positive_rates(
            empirical_meta.get("ranking_map_bucket_positive_rates")
        )
        train_diag = classification_diagnostics(train_scored["long_win"], train_scored["p_cal"])
        test_diag = classification_diagnostics(test_scored["long_win"], test_scored["p_cal"])
        bench_diag = benchmark_base_rate_metrics(test_scored["long_win"], train_df["long_win"])
        if len(full_imp):
            full_imp_copy = full_imp.copy()
            full_imp_copy["fold"] = fold_name
            all_feature_importance.append(full_imp_copy)
        if len(inner_imp):
            inner_imp_copy = inner_imp.copy()
            inner_imp_copy["fold"] = fold_name
            all_inner_feature_importance.append(inner_imp_copy)
        feature_validation_rows, feature_validation_daily_rows = feature_validation_for_fold(
            test_scored,
            feature_registry_df,
            fold_name,
        )
        all_feature_validation_rows.extend(feature_validation_rows)
        all_feature_validation_daily_rows.extend(feature_validation_daily_rows)

        fold_candidate_features: List[str] = []
        if len(full_imp):
            fold_candidate_features = (
                full_imp.groupby("feature", as_index=False)["importance"]
                .mean()
                .sort_values("importance", ascending=False)["feature"]
                .tolist()
            )
        fold_candidate_features = [feat for feat in fold_candidate_features if feat in features][:50]
        if not fold_candidate_features:
            raise RuntimeError(f"{fold_name}: discovery requires non-empty full-model feature importances.")

        best_subset_features: List[str] = []
        best_subset_score = float("-inf")
        subset_sizes = (8, 12, 16, 24, 32)
        for subset_size in subset_sizes:
            target_size = min(subset_size, len(fold_candidate_features))
            if target_size < 5:
                continue
            family_cap = max(1, int(math.ceil(target_size * 0.30)))
            selected_subset: List[str] = []
            family_counts: Dict[str, int] = defaultdict(int)
            for feat in fold_candidate_features:
                fam = str(feature_family_map.get(feat, "unknown"))
                if family_counts[fam] >= family_cap:
                    continue
                selected_subset.append(feat)
                family_counts[fam] += 1
                if len(selected_subset) >= target_size:
                    break
            if len(selected_subset) < max(5, int(target_size * 0.60)):
                continue
            y_sub_train = threshold_fit_df["long_win"].astype(int).values
            y_sub_holdout = threshold_holdout_df["long_win"].astype(int).values
            if len(np.unique(y_sub_train)) < 2 or len(np.unique(y_sub_holdout)) < 2:
                continue
            X_sub_train_raw = threshold_fit_df[selected_subset]
            X_sub_holdout_raw = threshold_holdout_df[selected_subset]
            X_sub_train, X_sub_holdout, _ = impute_fit_transform(X_sub_train_raw, X_sub_holdout_raw)
            subset_model = LogisticRegression(
                penalty="elasticnet",
                C=config.enet_c,
                l1_ratio=config.enet_l1_ratio,
                solver="saga",
                max_iter=2000,
                class_weight="balanced",
                random_state=config.random_seed + fold_num + target_size,
            )
            subset_model.fit(X_sub_train, y_sub_train)
            p_sub = subset_model.predict_proba(X_sub_holdout)[:, 1]
            subset_diag = classification_diagnostics(y_sub_holdout, p_sub)
            # Subset score uses classification metrics as a discovery proxy.
            # Final promotion is based on portfolio-level evaluation (research_score), not subset-search proxy.
            subset_score = (
                0.35 * float(cast(Any, subset_diag["pr_auc"]))
                + 0.25 * float(cast(Any, subset_diag["roc_auc"]))
                - 0.25 * float(cast(Any, subset_diag["log_loss"]))
                - 0.15 * float(cast(Any, subset_diag["brier"]))
            )
            if not np.isfinite(subset_score):
                continue
            subset_row = {
                "fold": fold_name,
                "subset_size": int(len(selected_subset)),
                "subset_score": float(subset_score),
                "holdout_pr_auc": float(subset_diag["pr_auc"]),
                "holdout_roc_auc": float(subset_diag["roc_auc"]),
                "holdout_log_loss": float(subset_diag["log_loss"]),
                "holdout_brier": float(subset_diag["brier"]),
                "selected_features_json": json.dumps(selected_subset),
            }
            all_subset_search_rows.append(subset_row)
            if subset_score > best_subset_score:
                best_subset_score = subset_score
                best_subset_features = selected_subset

        if not best_subset_features:
            raise RuntimeError(f"{fold_name}: subset search failed to produce a valid fold-safe feature subset.")

        selected_set = set(best_subset_features)
        for rank_idx, feat in enumerate(fold_candidate_features, start=1):
            row = {
                "fold": fold_name,
                "feature": feat,
                "family": str(feature_family_map.get(feat, "unknown")),
                "candidate_rank": rank_idx,
            }
            if feat in selected_set:
                all_selected_feature_rows.append(row)
            else:
                row["rejection_reason"] = "not_selected_in_fold_subset"
                all_rejected_feature_rows.append(row)

        y_perm_train = train_df["long_win"].astype(int).values
        y_perm_test = test_df["long_win"].astype(int).values
        if len(np.unique(y_perm_train)) < 2 or len(np.unique(y_perm_test)) < 2:
            raise RuntimeError(f"{fold_name}: permutation importance requires both classes in train/test.")
        X_perm_train_raw = train_df[best_subset_features]
        X_perm_test_raw = test_df[best_subset_features]
        X_perm_train, X_perm_test, perm_imp = impute_fit_transform(X_perm_train_raw, X_perm_test_raw)
        perm_model = LogisticRegression(
            penalty="elasticnet",
            C=config.enet_c,
            l1_ratio=config.enet_l1_ratio,
            solver="saga",
            max_iter=2000,
            class_weight="balanced",
            random_state=config.random_seed + fold_num + 10_000,
        )
        perm_model.fit(X_perm_train, y_perm_train)
        p_base = perm_model.predict_proba(X_perm_test)[:, 1]
        baseline_log_loss = float(log_loss(y_perm_test, clip_prob(p_base), labels=[0, 1]))
        rng = np.random.default_rng(config.random_seed + fold_num + 20_000)
        for feat in best_subset_features:
            shuffled = X_perm_test_raw.copy()
            shuffled[feat] = rng.permutation(shuffled[feat].values)
            X_perm = perm_imp.transform(shuffled)
            p_perm = perm_model.predict_proba(X_perm)[:, 1]
            perm_loss = float(log_loss(y_perm_test, clip_prob(p_perm), labels=[0, 1]))
            all_permutation_rows.append(
                {
                    "fold": fold_name,
                    "feature": feat,
                    "family": str(feature_family_map.get(feat, "unknown")),
                    "baseline_log_loss": baseline_log_loss,
                    "permuted_log_loss": perm_loss,
                    "log_loss_increase": perm_loss - baseline_log_loss,
                }
            )

        regime_specs: List[Tuple[str, pd.Series]] = []
        if "vol_cluster_high_34" in test_scored.columns:
            regime_specs.append(("high_vol_34", test_scored["vol_cluster_high_34"] >= 0.5))
        if "vol_cluster_low_34" in test_scored.columns:
            regime_specs.append(("low_vol_34", test_scored["vol_cluster_low_34"] >= 0.5))
        if not regime_specs:
            raise RuntimeError(f"{fold_name}: required volatility regime columns missing for regime_specific_importance.")
        for feat in best_subset_features:
            for regime_name, regime_mask in regime_specs:
                subset = test_scored.loc[regime_mask, [feat, "long_win"]].dropna()
                ic = spearman_ic(subset[feat], subset["long_win"], min_n=25) if len(subset) else {
                    "spearman_ic": np.nan,
                    "ic_std": np.nan,
                    "ic_hit_rate": np.nan,
                    "icir": np.nan,
                    "n_pairs": 0,
                }
                all_regime_rows.append(
                    {
                        "fold": fold_name,
                        "feature": feat,
                        "family": str(feature_family_map.get(feat, "unknown")),
                        "regime": regime_name,
                        "n_pairs": int(ic["n_pairs"]),
                        "spearman_ic": float(cast(Any, ic["spearman_ic"])) if np.isfinite(ic["spearman_ic"]) else np.nan,
                        "ic_hit_rate": float(cast(Any, ic["ic_hit_rate"])) if np.isfinite(ic["ic_hit_rate"]) else np.nan,
                        "icir": float(cast(Any, ic["icir"])) if np.isfinite(ic["icir"]) else np.nan,
                    }
                )

        contender_holdout_frames: Dict[str, pd.DataFrame] = {
            "incumbent_ml": threshold_holdout_scored.copy(),
        }
        contender_test_frames: Dict[str, pd.DataFrame] = {
            "incumbent_ml": test_scored.copy(),
        }
        baseline_linear_holdout, linear_holdout_meta = fit_linear_baseline_scored(
            threshold_fit_df,
            threshold_holdout_df,
            best_subset_features,
            config,
            seed=config.random_seed + fold_num,
        )
        baseline_linear_test, linear_test_meta = fit_linear_baseline_scored(
            train_df,
            test_df,
            best_subset_features,
            config,
            seed=config.random_seed + 1_000 + fold_num,
        )
        contender_holdout_frames["baseline_linear"] = baseline_linear_holdout
        contender_test_frames["baseline_linear"] = baseline_linear_test
        baseline_rank_holdout, rank_holdout_meta = fit_equal_weight_rank_blend_scored(
            threshold_fit_df,
            threshold_holdout_df,
            best_subset_features,
            feature_registry_df,
            feature_family_map,
            config,
        )
        baseline_rank_test, rank_test_meta = fit_equal_weight_rank_blend_scored(
            train_df,
            test_df,
            best_subset_features,
            feature_registry_df,
            feature_family_map,
            config,
        )
        contender_holdout_frames["baseline_equal_weight_rank_blend"] = baseline_rank_holdout
        contender_test_frames["baseline_equal_weight_rank_blend"] = baseline_rank_test
        contender_meta = {
            "baseline_linear": {**linear_holdout_meta, **linear_test_meta},
            "baseline_equal_weight_rank_blend": {**rank_holdout_meta, **rank_test_meta},
            "incumbent_ml": {
                "baseline_feature_count": int(len(best_subset_features)),
                "baseline_status": "ok",
                "selected_features_json": json.dumps(best_subset_features),
            },
        }
        for contender_name in ("baseline_linear", "baseline_equal_weight_rank_blend", "incumbent_ml"):
            contender_row = evaluate_model_contender(
                contender_name,
                fold_name,
                contender_holdout_frames[contender_name],
                contender_test_frames[contender_name],
                test_df,
                config,
            )
            contender_row.update(contender_meta.get(contender_name, {}))
            all_model_comparison_rows.append(contender_row)

        fold_rows: List[Dict[str, Any]] = []
        for max_concurrent in config.max_concurrent_options:
            thresholds, threshold_candidate_df, wrc_summary = choose_thresholds(threshold_holdout_scored, config, fold_name, max_concurrent)
            fold_selected = int(wrc_summary.get("wrc_pass", 0) == 1)
            fold_skip_reason = "" if fold_selected else str(wrc_summary.get("wrc_status", "wrc_fail"))
            all_thresholds.append({
                "fold": fold_name,
                "max_concurrent": max_concurrent,
                "p_min": thresholds["p_min"],
                "theta_ev": thresholds["theta_ev"],
                "theta_rel": thresholds["theta_rel"],
                "score": thresholds["score"],
                "wrc_status": wrc_summary.get("wrc_status"),
                "wrc_pvalue": wrc_summary.get("wrc_pvalue"),
                "fold_selected": fold_selected,
                "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
                "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
                "trial_scope_formal": TRIAL_SCOPE_FORMAL,
                "trial_count_formal": int(threshold_policy_trial_count(config)),
                "schema_version": SCHEMA_VERSION,
                "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
                "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
                "implementation_status": config.implementation_status,
                "verification_stage_reached": config.verification_stage_reached,
            })
            if len(threshold_candidate_df):
                threshold_candidate_df = threshold_candidate_df.copy()
                threshold_candidate_df["fold"] = fold_name
                all_threshold_candidate_rows.extend(threshold_candidate_df.to_dict("records"))
            trades, equity, metrics = simulate_book(
                test_scored,
                config=config,
                max_concurrent=max_concurrent,
                p_min=thresholds["p_min"],
                theta_ev=thresholds["theta_ev"],
                theta_rel=thresholds["theta_rel"],
                fold_name=f"{fold_name}_slots_{max_concurrent}",
                audit_sink=all_position_ranking_rows,
            )
            ic_binary = spearman_ic(test_scored["p_cal"], test_scored["long_win"])
            ic_r_mult = spearman_ic(
                trades["p_entry"], trades["r_multiple"]
            ) if len(trades) >= 5 and "p_entry" in trades.columns and "r_multiple" in trades.columns else {
                "spearman_ic": np.nan, "ic_std": np.nan, "ic_hit_rate": np.nan, "icir": np.nan, "n_pairs": 0,
            }
            # Blueprint-style timestamp-level IC (MR3)
            _, ic_ts_summary = spearman_ic_by_timestamp(
                test_scored,
                score_col="p_cal",
                outcome_col="long_win",
                timestamp_col="timestamp_utc",
                min_n=5,
            )
            policy_daily = build_daily_equity_frame(
                equity if fold_selected else pd.DataFrame(),
                session_dates_from_frame(test_df),
                config.starting_capital,
                max_concurrent,
            )
            if len(policy_daily):
                policy_daily["fold"] = fold_name
                policy_daily["max_concurrent"] = int(max_concurrent)
                policy_daily["fold_selected"] = int(fold_selected)
                policy_daily["fold_skip_reason"] = fold_skip_reason
                policy_daily["schema_version"] = SCHEMA_VERSION
                policy_daily["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
                policy_daily["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
                policy_daily["implementation_status"] = config.implementation_status
                policy_daily["verification_stage_reached"] = config.verification_stage_reached
                policy_daily["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
                policy_daily["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
                policy_daily["trial_scope_formal"] = TRIAL_SCOPE_FORMAL
                policy_daily["trial_count_formal"] = int(threshold_policy_trial_count(config))
                all_policy_daily_rows.extend(policy_daily.to_dict("records"))
            fold_metrics_row: Dict[str, Any] = {
                **metrics,
                "spearman_ic_binary": ic_binary["spearman_ic"],
                "spearman_ic_r_multiple": ic_r_mult["spearman_ic"],
                "ic_n_pairs_binary": ic_binary["n_pairs"],
                "ic_n_pairs_r_multiple": ic_r_mult["n_pairs"],
                "ic_timestamp_mean": ic_ts_summary.get("mean_ic", math.nan),
                "ic_timestamp_ir": ic_ts_summary.get("ic_ir", math.nan),
                "ic_timestamp_hit_rate": ic_ts_summary.get("positive_ic_hit_rate", math.nan),
                "ic_n_timestamps": ic_ts_summary.get("n_timestamps", 0),
                "fold": fold_name,
                "max_concurrent": max_concurrent,
                "train_rows": len(train_df),
                "test_rows": len(test_df),
                "threshold_score": thresholds["score"],
                "p_min": thresholds["p_min"],
                "theta_ev": thresholds["theta_ev"],
                "theta_rel": thresholds["theta_rel"],
                "train_pos_rate": float(train_df["long_win"].mean()),
                "test_pos_rate": float(test_df["long_win"].mean()),
                "threshold_holdout_rows": len(threshold_holdout_scored),
                "threshold_holdout_pos_rate": float(threshold_holdout_scored["long_win"].mean()),
                "threshold_holdout_log_loss": th_holdout_diag["log_loss"],
                "threshold_holdout_brier": th_holdout_diag["brier"],
                "threshold_holdout_roc_auc": th_holdout_diag["roc_auc"],
                "threshold_holdout_pr_auc": th_holdout_diag["pr_auc"],
                "wrc_pvalue": wrc_summary.get("wrc_pvalue"),
                "wrc_status": wrc_summary.get("wrc_status"),
                "wrc_pass": wrc_summary.get("wrc_pass"),
                "wrc_observed_best_mean": wrc_summary.get("observed_best_mean"),
                "threshold_family_candidate_count": wrc_summary.get("threshold_family_candidate_count"),
                "trial_scope_formal": wrc_summary.get("trial_scope_formal"),
                "trial_count_formal": wrc_summary.get("trial_count_formal"),
                "fold_selected": fold_selected,
                "fold_skip_reason": fold_skip_reason,
                "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
                "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
                "schema_version": SCHEMA_VERSION,
                "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
                "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
                "implementation_status": config.implementation_status,
                "verification_stage_reached": config.verification_stage_reached,
                "scorecard_label": SCORECARD_LABEL,
                "scorecard_archetype": SCORECARD_ARCHETYPE,
                "empirical_prob_map_status_threshold": threshold_empirical_meta.get("empirical_prob_map_status"),
                "empirical_prob_map_support_rows_threshold": threshold_empirical_meta.get("empirical_prob_map_support_rows"),
                "empirical_prob_map_status_test": empirical_meta.get("empirical_prob_map_status"),
                "empirical_prob_map_support_rows_test": empirical_meta.get("empirical_prob_map_support_rows"),
                "ranking_map_max_fallback_usage_fraction_allowed": threshold_empirical_meta.get(
                    "ranking_map_max_fallback_usage_fraction_allowed"
                ),
                "ranking_map_min_adjacent_fold_spearman_allowed": threshold_empirical_meta.get(
                    "ranking_map_min_adjacent_fold_spearman_allowed"
                ),
                "calibration_holdout_rows": calib_stats.get("calibration_holdout_rows"),
                "calibration_holdout_pos_rate": calib_stats.get("calibration_holdout_pos_rate"),
                "calibration_holdout_pos_count": calib_stats.get("calibration_holdout_pos_count"),
                "calibration_holdout_neg_count": calib_stats.get("calibration_holdout_neg_count"),
                "train_roc_auc": train_diag["roc_auc"],
                "test_roc_auc": test_diag["roc_auc"],
                "train_pr_auc": train_diag["pr_auc"],
                "test_pr_auc": test_diag["pr_auc"],
                "train_log_loss": train_diag["log_loss"],
                "test_log_loss": test_diag["log_loss"],
                "train_brier": train_diag["brier"],
                "test_brier": test_diag["brier"],
                **_ranking_map_artifact_fields(threshold_empirical_meta, suffix="threshold_holdout"),
                **_ranking_map_artifact_fields(empirical_meta, suffix="test"),
                **_optuna_artifact_fields(
                    cast(Mapping[str, Any], threshold_empirical_meta.get("optuna_summary", {})),
                    prefix="threshold_fit",
                ),
                **_optuna_artifact_fields(
                    cast(Mapping[str, Any], calib_stats.get("optuna_summary", {})),
                    prefix="outer_fit",
                ),
                **bench_diag,
            }
            all_fold_metrics.append(fold_metrics_row)
            fold_rows.append(fold_metrics_row)
            all_fold_ic.append({
                "fold": fold_name,
                "max_concurrent": max_concurrent,
                "spearman_ic_binary": ic_binary["spearman_ic"],
                "ic_std_binary": ic_binary["ic_std"],
                "ic_hit_rate_binary": ic_binary["ic_hit_rate"],
                "icir_binary": ic_binary["icir"],
                "n_pairs_binary": ic_binary["n_pairs"],
                "spearman_ic_r_multiple": ic_r_mult["spearman_ic"],
                "ic_std_r_multiple": ic_r_mult["ic_std"],
                "ic_hit_rate_r_multiple": ic_r_mult["ic_hit_rate"],
                "icir_r_multiple": ic_r_mult["icir"],
                "n_pairs_r_multiple": ic_r_mult["n_pairs"],
                "ic_timestamp_mean": ic_ts_summary.get("mean_ic", math.nan),
                "ic_timestamp_ir": ic_ts_summary.get("ic_ir", math.nan),
                "ic_timestamp_hit_rate": ic_ts_summary.get("positive_ic_hit_rate", math.nan),
                "ic_n_timestamps": ic_ts_summary.get("n_timestamps", 0),
                "wrc_pvalue": wrc_summary.get("wrc_pvalue"),
                "wrc_status": wrc_summary.get("wrc_status"),
                "fold_selected": fold_selected,
            })
            log_fold_metrics_summary(fold_metrics_row)
            if len(trades) and fold_selected:
                trades = trades.copy()
                trades["max_concurrent"] = max_concurrent
                trades["fold"] = fold_name
                trades["fold_selected"] = int(fold_selected)
                all_trades.append(trades)
            if len(equity) and fold_selected:
                equity = equity.copy()
                equity["max_concurrent"] = max_concurrent
                equity["fold"] = fold_name
                equity["fold_selected"] = int(fold_selected)
                all_equity.append(equity)
        if fold_rows:
            def _safe_float(x: object) -> float:
                try:
                    xf = float(cast(Any, x))
                    return xf if np.isfinite(xf) else float("-inf")
                except Exception:
                    return float("-inf")

            best_threshold_score = max((_safe_float(r.get("threshold_score")) for r in fold_rows), default=float("-inf"))
            best_calmar = max((_safe_float(r.get("calmar")) for r in fold_rows), default=float("-inf"))

            def _pf_rank(x: object) -> float:
                try:
                    xf = float(cast(Any, x))
                    if xf == float("inf"):
                        return float("inf")
                    return xf if np.isfinite(xf) else float("-inf")
                except Exception:
                    return float("-inf")

            best_profit_factor_rank = max((_pf_rank(r.get("profit_factor")) for r in fold_rows), default=float("-inf"))
            best_profit_factor_text = "n/a"
            if best_profit_factor_rank == float("inf"):
                best_profit_factor_text = "inf"
            elif np.isfinite(best_profit_factor_rank) and best_profit_factor_rank != float("-inf"):
                best_profit_factor_text = f"{best_profit_factor_rank:.2f}"

            logging.info(
                "Fold Complete | %s | variants=%s | best_threshold_score=%s | best_calmar=%s | best_profit_factor=%s",
                fold_name,
                len(fold_rows),
                ("n/a" if best_threshold_score == float("-inf") else f"{best_threshold_score:.2f}"),
                ("n/a" if best_calmar == float("-inf") else f"{best_calmar:.2f}"),
                best_profit_factor_text,
            )
        completed_fold_names = completed_fold_names + [fold_name]
        previous_threshold_bucket_positive_rates = current_threshold_bucket_positive_rates
        previous_test_bucket_positive_rates = current_test_bucket_positive_rates
        atomic_write_json(
            resume_path,
            {
                "resume_fingerprint": resume_fingerprint,
                "schema_version": SCHEMA_VERSION,
                "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
                "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
                "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
                "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
                "trial_scope_formal": TRIAL_SCOPE_FORMAL,
                "trial_count_formal": int(threshold_policy_trial_count(config)),
                "implementation_status": config.implementation_status,
                "verification_stage_reached": config.verification_stage_reached,
                "last_completed_fold": fold_num,
                "completed_fold_names": completed_fold_names,
            },
        )
        atomic_write_csv(pd.DataFrame(all_fold_metrics), paths.metrics_dir / "fold_metrics.csv")
        if all_fold_ic:
            atomic_write_csv(pd.DataFrame(all_fold_ic), paths.metrics_dir / "fold_ic_summary.csv")
        if all_trades:
            atomic_write_csv(pd.concat(all_trades, ignore_index=True), paths.metrics_dir / "trade_blotter.csv")
        if all_equity:
            atomic_write_csv(pd.concat(all_equity, ignore_index=True), paths.metrics_dir / "equity_curves.csv")
        if all_feature_importance:
            atomic_write_csv(pd.concat(all_feature_importance, ignore_index=True), paths.features_dir / "feature_importances_by_fold.csv")
        if all_inner_feature_importance:
            atomic_write_csv(pd.concat(all_inner_feature_importance, ignore_index=True), paths.features_dir / "inner_feature_importances_by_fold.csv")
        if all_threshold_candidate_rows:
            atomic_write_csv(pd.DataFrame(all_threshold_candidate_rows), paths.metrics_dir / "threshold_candidate_diagnostics.csv")
        if all_policy_daily_rows:
            atomic_write_csv(pd.DataFrame(all_policy_daily_rows), paths.metrics_dir / "policy_daily_returns.csv")
        if all_feature_validation_rows:
            atomic_write_csv(pd.DataFrame(all_feature_validation_rows), paths.features_dir / "feature_validation_rows.csv")
        if all_feature_validation_daily_rows:
            atomic_write_csv(pd.DataFrame(all_feature_validation_daily_rows), paths.features_dir / "feature_validation_ic_daily_rows.csv")
        if all_model_comparison_rows:
            atomic_write_csv(pd.DataFrame(all_model_comparison_rows), paths.strategies_dir / "model_comparison_report_rows.csv")
        if all_position_ranking_rows:
            atomic_write_csv(pd.DataFrame(all_position_ranking_rows), paths.strategies_dir / "position_ranking_audit.csv")
        if all_subset_search_rows:
            atomic_write_csv(pd.DataFrame(all_subset_search_rows), paths.features_dir / "subset_search_summary.csv")
        if all_selected_feature_rows:
            atomic_write_csv(pd.DataFrame(all_selected_feature_rows), paths.features_dir / "selected_features_by_fold.csv")
        if all_rejected_feature_rows:
            atomic_write_csv(pd.DataFrame(all_rejected_feature_rows), paths.features_dir / "rejected_features_by_fold.csv")
        if all_permutation_rows:
            atomic_write_csv(pd.DataFrame(all_permutation_rows), paths.features_dir / "permutation_importance.csv")
        if all_regime_rows:
            atomic_write_csv(pd.DataFrame(all_regime_rows), paths.features_dir / "regime_specific_importance.csv")
        logging.info("Resume: saved state after %s (%s folds completed)", fold_name, len(completed_fold_names))
    fold_metrics_df = pd.DataFrame(all_fold_metrics)
    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    equity_df = pd.concat(all_equity, ignore_index=True) if all_equity else pd.DataFrame()
    policy_daily_df = pd.DataFrame(all_policy_daily_rows)
    threshold_candidate_df = pd.DataFrame(all_threshold_candidate_rows)
    feature_importance_df = pd.concat(all_feature_importance, ignore_index=True) if all_feature_importance else pd.DataFrame()
    if len(fold_metrics_df):
        by_conc = fold_metrics_df.groupby("max_concurrent").agg(
            n_trades=("n_trades", "sum"),
            avg_calmar=("calmar", "mean"),
            avg_pf=("profit_factor", "mean"),
            avg_expectancy_r=("expectancy_r", "mean"),
            avg_cagr=("cagr", "mean"),
            avg_mdd=("mdd", "mean"),
            avg_churn=("churn", "mean"),
        ).reset_index()
    else:
        by_conc = pd.DataFrame()
    best_concurrent = int(config.max_concurrent_options[0])
    if len(by_conc):
        by_conc = by_conc.sort_values("max_concurrent").reset_index(drop=True)
    trades_best = trades_df[trades_df["max_concurrent"] == best_concurrent].copy() if len(trades_df) else pd.DataFrame()
    equity_best = chain_equity_curves(equity_df, best_concurrent, config.starting_capital)
    policy_daily_best_raw = (
        policy_daily_df[policy_daily_df["max_concurrent"] == best_concurrent].copy()
        if len(policy_daily_df)
        else pd.DataFrame()
    )
    stitched_policy_daily, stitched_policy_summary = summarize_stitched_policy_daily(
        policy_daily_best_raw,
        starting_capital=config.starting_capital,
        trial_count=threshold_policy_trial_count(config),
    )
    fold_metrics_best = (
        fold_metrics_df[fold_metrics_df["max_concurrent"] == best_concurrent].copy()
        if len(fold_metrics_df)
        else pd.DataFrame()
    )
    overall_metrics = compute_metrics(trades_best, equity_best, config)
    overall_metrics["best_max_concurrent"] = best_concurrent
    overall_metrics["max_concurrent_is_cap_only"] = True
    overall_metrics["n_folds"] = int(len(fold_metrics_best))
    overall_metrics["n_selected_folds"] = int(fold_metrics_best["fold_selected"].sum()) if len(fold_metrics_best) and "fold_selected" in fold_metrics_best.columns else 0
    overall_metrics["n_skipped_folds"] = int(overall_metrics["n_folds"] - overall_metrics["n_selected_folds"])
    overall_metrics["fold_skip_rate"] = (
        float(overall_metrics["n_skipped_folds"] / overall_metrics["n_folds"])
        if overall_metrics["n_folds"] > 0
        else 0.0
    )
    overall_metrics["churn"] = float(trades_best["replacement_exit"].mean()) if "replacement_exit" in trades_best.columns and len(trades_best) else 0.0
    overall_metrics.update(stitched_policy_summary)
    overall_metrics["stitched_policy_days"] = int(len(stitched_policy_daily))
    if len(stitched_policy_daily):
        overall_metrics["stitched_policy_start"] = str(stitched_policy_daily["session_date_ny"].iloc[0])
        overall_metrics["stitched_policy_end"] = str(stitched_policy_daily["session_date_ny"].iloc[-1])
    else:
        overall_metrics["stitched_policy_start"] = None
        overall_metrics["stitched_policy_end"] = None
    if len(fold_metrics_best):
        wrc_status = fold_metrics_best["wrc_status"].astype(str)
        evaluable = wrc_status.isin(["pass", "fail"])
        overall_metrics["white_rc_pass_rate"] = float((wrc_status == "pass").mean())
        overall_metrics["wrc_evaluable_fold_count"] = int(evaluable.sum())
        overall_metrics["wrc_pass_count"] = int((wrc_status == "pass").sum())
        overall_metrics["wrc_fail_count"] = int((wrc_status == "fail").sum())
        overall_metrics["wrc_insufficient_count"] = int((wrc_status == "insufficient_data").sum())
    else:
        overall_metrics["white_rc_pass_rate"] = 0.0
        overall_metrics["wrc_evaluable_fold_count"] = 0
        overall_metrics["wrc_pass_count"] = 0
        overall_metrics["wrc_fail_count"] = 0
        overall_metrics["wrc_insufficient_count"] = 0
    overall_metrics["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
    overall_metrics["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
    overall_metrics["trial_scope_formal"] = TRIAL_SCOPE_FORMAL
    overall_metrics["trial_count_formal"] = int(threshold_policy_trial_count(config))
    if "feature_set_version" not in config_snapshot_payload and features:
        config_snapshot_payload["feature_set_version"] = build_feature_set_version(features)
        verification["feature_set_version"] = config_snapshot_payload["feature_set_version"]
    overall_metrics["schema_version"] = SCHEMA_VERSION
    overall_metrics["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
    overall_metrics["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
    overall_metrics["dataset_build_id"] = config_snapshot_payload.get("dataset_build_id")
    overall_metrics["export_panel_version_id"] = config_snapshot_payload.get("export_panel_version_id")
    overall_metrics["feature_set_version"] = config_snapshot_payload.get("feature_set_version")
    overall_metrics["implementation_status"] = (
        config.implementation_status if config.implementation_status in IMPLEMENTATION_STATUS_VALUES else "present"
    )
    overall_metrics["verification_stage_reached"] = str(config.verification_stage_reached)
    overall_metrics["scorecard_label"] = SCORECARD_LABEL
    overall_metrics["scorecard_archetype"] = SCORECARD_ARCHETYPE
    overall_metrics["code_fingerprint"] = code_fingerprint
    overall_metrics["input_data_hash"] = input_data_hash
    overall_metrics["config_hash"] = config_hash
    if len(trades_best):
        per_ticker = trades_best.groupby("ticker")["pnl"].sum().abs()
        top_share_abs = float(per_ticker.max() / per_ticker.sum()) if per_ticker.sum() > 0 else 1.0
    else:
        top_share_abs = 1.0
    fold_expectancies = (
        fold_metrics_df[fold_metrics_df["max_concurrent"] == best_concurrent]["expectancy_r"].tolist()
        if len(fold_metrics_df) else []
    )
    research_input = dict(overall_metrics)
    research_input["calmar"] = float(overall_metrics.get("stitched_daily_calmar", overall_metrics.get("daily_calmar", overall_metrics.get("calmar", 0.0))))
    research_input["mdd"] = float(overall_metrics.get("stitched_daily_mdd", overall_metrics.get("daily_mdd", overall_metrics.get("mdd", 0.0))))
    research_input["cagr"] = float(overall_metrics.get("stitched_daily_cagr", overall_metrics.get("daily_cagr", overall_metrics.get("cagr", 0.0))))
    research, research_meta = research_score(research_input, fold_expectancies, top_share_abs)
    overall_metrics["research_score"] = research
    overall_metrics.update(research_meta)
    capacity_eval = evaluate_capacity_rule_compliance(trades_best, config)
    regime_eval = evaluate_regime_diversity_policy(trades_best)
    capacity_headroom = capacity_headroom_metrics(trades_best, overall_metrics, config)
    overall_metrics.update(capacity_eval)
    overall_metrics.update(capacity_headroom)
    overall_metrics.update(regime_eval)
    overall_metrics["n_positive_folds"] = int((fold_metrics_best["expectancy_r"].astype(float) > 0).sum()) if len(fold_metrics_best) else 0
    overall_metrics["positive_fold_fraction"] = (
        float((fold_metrics_best["expectancy_r"].astype(float) > 0).mean()) if len(fold_metrics_best) else 0.0
    )
    overall_metrics.update(summarize_ranking_map_guardrails(fold_metrics_best, config))
    overall_metrics["chronology_checks_pass"] = True
    overall_metrics["sufficient_stitched_oos"] = bool(
        int(overall_metrics.get("n_daily_observations", 0)) >= int(config.final_min_oos_daily_observations)
    )
    robustness_failures: List[str] = []
    if not bool(overall_metrics["chronology_checks_pass"]):
        robustness_failures.append("chronology_checks_failed")
    if not bool(overall_metrics.get("capacity_rule_compliant", False)):
        robustness_failures.append("capacity_rule_violation")
    if not bool(overall_metrics.get("sufficient_stitched_oos", False)):
        robustness_failures.append("insufficient_stitched_oos")
    if not bool(overall_metrics.get("ranking_map_guardrails_pass", False)):
        robustness_failures.append("ranking_map_guardrail_breach")
    deflated_sharpe_value = float(overall_metrics.get("deflated_sharpe_daily", np.nan))
    if (not np.isfinite(deflated_sharpe_value)) or deflated_sharpe_value <= 0:
        robustness_failures.append("deflated_sharpe_non_positive")
    policy_failures: List[str] = []
    if float(overall_metrics.get("stitched_daily_calmar", 0.0)) < 0.75:
        policy_failures.append("stitched_daily_calmar_below_0.75")
    if float(overall_metrics.get("stitched_daily_mdd", 1.0)) > 0.25:
        policy_failures.append("stitched_daily_mdd_above_0.25")
    if float(overall_metrics.get("expectancy_r", 0.0)) <= 0:
        policy_failures.append("expectancy_r_non_positive")
    if not bool(overall_metrics.get("regime_diversity_policy_pass", False)):
        policy_failures.append(str(overall_metrics.get("regime_diversity_policy_reason", "regime_diversity_policy_fail")))
    overall_metrics["robustness_pass"] = len(robustness_failures) == 0
    overall_metrics["portfolio_policy_pass"] = len(policy_failures) == 0
    overall_metrics["promotion_pass"] = bool(overall_metrics["robustness_pass"] and overall_metrics["portfolio_policy_pass"])
    overall_metrics["robustness_reason"] = "ok" if overall_metrics["robustness_pass"] else ";".join(robustness_failures)
    overall_metrics["portfolio_policy_reason"] = "ok" if overall_metrics["portfolio_policy_pass"] else ";".join(policy_failures)
    overall_metrics.update(evaluate_scorecard_defaults(overall_metrics))
    log_overall_summary(overall_metrics)
    if fold_metrics_df.empty:
        raise RuntimeError("No outer folds completed successfully; cannot build required strategy/discovery outputs.")
    if feature_importance_df.empty:
        raise RuntimeError("Missing feature_importances_by_fold; discovery outputs require real fold-level importances.")
    if not all_subset_search_rows:
        raise RuntimeError("Missing subset_search_summary rows; subset search must run fold-safe within each outer fold.")
    if not all_selected_feature_rows:
        raise RuntimeError("Missing selected_features_by_fold rows; cannot compute fold stability.")
    if not all_permutation_rows:
        raise RuntimeError("Missing permutation_importance rows; ablation outputs require real fold-safe permutations.")
    if not all_regime_rows:
        raise RuntimeError("Missing regime_specific_importance rows; regime diagnostics require fold-level computation.")

    feature_stability = (
        feature_importance_df.groupby("feature")["importance"]
        .agg(["mean", "median", "std", "count"])
        .reset_index()
        .sort_values("mean", ascending=False)
    )
    ranked_feature_table = feature_stability.rename(
        columns={"mean": "mean_importance", "median": "median_importance", "std": "std_importance", "count": "n_rows"}
    ).copy()
    ranked_feature_table["rank"] = np.arange(1, len(ranked_feature_table) + 1)

    fi_mapped = feature_importance_df.merge(
        feature_registry_df[["feature_name", "family", "regular_or_physics"]],
        left_on="feature",
        right_on="feature_name",
        how="left",
    )
    family_importance_table = (
        fi_mapped.groupby(["family", "regular_or_physics"], dropna=False)["importance"]
        .agg(["mean", "median", "std", "count"])
        .reset_index()
        .rename(
            columns={
                "mean": "mean_importance",
                "median": "median_importance",
                "std": "std_importance",
                "count": "n_rows",
            }
        )
        .sort_values("mean_importance", ascending=False)
    )
    per_model_feature = (
        feature_importance_df.groupby(["model", "feature"], as_index=False)["importance"]
        .mean()
    )
    per_model_feature["model_rank_norm"] = per_model_feature.groupby("model")["importance"].rank(pct=True)
    ensemble_importance = (
        per_model_feature.groupby("feature", as_index=False)
        .agg(
            ensemble_score=("model_rank_norm", "mean"),
            mean_importance=("importance", "mean"),
            model_coverage=("model", "nunique"),
        )
        .sort_values("ensemble_score", ascending=False)
    )

    subset_search_summary = pd.DataFrame(all_subset_search_rows).sort_values(
        ["fold", "subset_score"], ascending=[True, False]
    )
    selected_by_fold = pd.DataFrame(all_selected_feature_rows)
    n_completed_folds = max(1, len(set(completed_fold_names)))
    fold_stability_table = (
        selected_by_fold.groupby("feature", as_index=False)
        .agg(n_folds_selected=("fold", "nunique"))
    )
    fold_stability_table["fold_stability"] = fold_stability_table["n_folds_selected"] / n_completed_folds
    fold_stability_table = fold_stability_table.merge(
        feature_stability[["feature", "mean", "std"]],
        on="feature",
        how="left",
    ).rename(columns={"mean": "mean_importance", "std": "std_importance"})
    fold_stability_table = fold_stability_table.sort_values(
        ["fold_stability", "mean_importance"], ascending=[False, False]
    )

    permutation_raw = pd.DataFrame(all_permutation_rows)
    permutation_importance = (
        permutation_raw.groupby(["feature", "family"], as_index=False)
        .agg(
            mean_log_loss_increase=("log_loss_increase", "mean"),
            median_log_loss_increase=("log_loss_increase", "median"),
            std_log_loss_increase=("log_loss_increase", "std"),
            n_permutations=("log_loss_increase", "count"),
        )
        .sort_values("mean_log_loss_increase", ascending=False)
    )
    feature_ablation = permutation_importance.copy()
    feature_ablation["ablation_score"] = feature_ablation["mean_log_loss_increase"]
    family_ablation = (
        permutation_raw.groupby("family", as_index=False)
        .agg(
            mean_log_loss_increase=("log_loss_increase", "mean"),
            median_log_loss_increase=("log_loss_increase", "median"),
            std_log_loss_increase=("log_loss_increase", "std"),
            n_permutations=("log_loss_increase", "count"),
        )
        .sort_values("mean_log_loss_increase", ascending=False)
    )
    family_ablation["ablation_score"] = family_ablation["mean_log_loss_increase"]
    family_ablation = family_ablation.rename(columns={"family": "family_name"})

    regime_specific_importance = (
        pd.DataFrame(all_regime_rows)
        .groupby(["feature", "family", "regime"], as_index=False)
        .agg(
            mean_spearman_ic=("spearman_ic", "mean"),
            median_spearman_ic=("spearman_ic", "median"),
            mean_icir=("icir", "mean"),
            mean_ic_hit_rate=("ic_hit_rate", "mean"),
            n_pairs=("n_pairs", "sum"),
            n_folds_seen=("fold", "nunique"),
        )
        .sort_values(["regime", "mean_spearman_ic"], ascending=[True, False])
    )

    feature_validation_rows_df = ensure_columns(pd.DataFrame(all_feature_validation_rows), FEATURE_VALIDATION_ROW_COLUMNS)
    feature_validation_daily_df = ensure_columns(pd.DataFrame(all_feature_validation_daily_rows), FEATURE_VALIDATION_DAILY_COLUMNS)
    feature_validation_report = build_feature_validation_report(
        feature_validation_rows_df,
        feature_validation_daily_df,
        feature_registry_df,
    )
    for frame in (feature_validation_rows_df, feature_validation_daily_df, feature_validation_report):
        frame["schema_version"] = SCHEMA_VERSION
        frame["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
        frame["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
        frame["implementation_status"] = config.implementation_status
        frame["verification_stage_reached"] = config.verification_stage_reached
        frame["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
        frame["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
        frame["trial_scope_formal"] = TRIAL_SCOPE_FORMAL
        frame["trial_count_formal"] = int(threshold_policy_trial_count(config))

    model_comparison_rows_df = ensure_columns(pd.DataFrame(all_model_comparison_rows), MODEL_COMPARISON_ROW_COLUMNS)
    model_comparison_report = build_model_comparison_report(model_comparison_rows_df)
    model_comparison_rows_df["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
    model_comparison_rows_df["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
    model_comparison_rows_df["trial_scope_formal"] = TRIAL_SCOPE_FORMAL
    model_comparison_rows_df["trial_count_formal"] = int(threshold_policy_trial_count(config))
    model_comparison_rows_df["implementation_status"] = config.implementation_status
    model_comparison_rows_df["verification_stage_reached"] = config.verification_stage_reached
    model_comparison_report["implementation_status"] = config.implementation_status
    model_comparison_report["verification_stage_reached"] = config.verification_stage_reached
    model_comparison_pass = bool(
        len(model_comparison_report)
        and int(
            model_comparison_report.loc[
                model_comparison_report["model_name"] == "incumbent_ml",
                "model_comparison_pass",
            ].fillna(0).max()
        )
        == 1
    )
    overall_metrics["model_comparison_pass"] = model_comparison_pass
    validated_feature_names: Set[str] = set()
    if len(feature_validation_report):
        validated_feature_names = set(
            feature_validation_report.loc[
                feature_validation_report["feature_validation_pass"].astype(int) == 1,
                "feature",
            ].astype(str).tolist()
        )
    overall_metrics["feature_validation_pass"] = False

    candidate_features = fold_stability_table.merge(
        permutation_importance[["feature", "mean_log_loss_increase"]],
        on="feature",
        how="left",
    )
    candidate_features = candidate_features.merge(
        feature_registry_df[["feature_name", "family"]],
        left_on="feature",
        right_on="feature_name",
        how="left",
    )
    candidate_features["family"] = candidate_features["family"].fillna("unknown")
    candidate_features["mean_log_loss_increase"] = candidate_features["mean_log_loss_increase"].fillna(0.0)
    candidate_features["stability_rank_norm"] = candidate_features["fold_stability"].rank(pct=True)
    candidate_features["ablation_rank_norm"] = candidate_features["mean_log_loss_increase"].rank(pct=True)
    candidate_features["feature_validation_pass"] = candidate_features["feature"].isin(validated_feature_names).astype(int)
    candidate_features["discovery_score"] = (
        0.60 * candidate_features["stability_rank_norm"] + 0.40 * candidate_features["ablation_rank_norm"]
    )
    candidate_features = candidate_features.sort_values(
        ["discovery_score", "fold_stability", "mean_importance"],
        ascending=[False, False, False],
    )
    selection_pool = candidate_features[candidate_features["feature_validation_pass"] == 1].copy()
    selection_pool_reason = "validated_only"
    if selection_pool.empty:
        selection_pool = candidate_features.copy()
        selection_pool_reason = "fallback_any_discovery"
    selected_rows: List[Dict[str, Any]] = []
    family_counter: Dict[str, int] = defaultdict(int)
    max_selected = 30
    family_cap = max(1, int(math.ceil(max_selected * 0.30)))
    for row in selection_pool.itertuples(index=False):
        if float(cast(Any, row.fold_stability)) < 0.50:
            continue
        fam = str(cast(Any, row.family))
        if family_counter[fam] >= family_cap:
            continue
        selected_rows.append(
            {
                "feature": str(cast(Any, row.feature)),
                "family": fam,
                "fold_stability": float(cast(Any, row.fold_stability)),
                "mean_importance": float(cast(Any, row.mean_importance)) if pd.notna(row.mean_importance) else np.nan,
                "mean_log_loss_increase": float(cast(Any, row.mean_log_loss_increase)),
                "discovery_score": float(cast(Any, row.discovery_score)),
                "feature_validation_pass": int(cast(Any, row.feature_validation_pass)),
                "selection_pool_reason": selection_pool_reason,
            }
        )
        family_counter[fam] += 1
        if len(selected_rows) >= max_selected:
            break
    selected_final_feature_set = pd.DataFrame(selected_rows)
    if selected_final_feature_set.empty:
        raise RuntimeError("No stable final feature set could be selected under fold stability and family-cap constraints.")
    selected_features_validated = int(selected_final_feature_set["feature_validation_pass"].sum()) if "feature_validation_pass" in selected_final_feature_set.columns else 0
    selected_feature_count = int(len(selected_final_feature_set))
    overall_metrics["selected_feature_count"] = selected_feature_count
    overall_metrics["selected_validated_feature_count"] = selected_features_validated
    overall_metrics["selected_validated_feature_fraction"] = (
        float(selected_features_validated / selected_feature_count) if selected_feature_count > 0 else 0.0
    )
    overall_metrics["selected_feature_validation_pool"] = selection_pool_reason
    overall_metrics["feature_validation_pass"] = bool(
        selected_feature_count > 0
        and selected_features_validated == selected_feature_count
        and len(validated_feature_names) > 0
    )

    rejected_unstable_features = candidate_features[candidate_features["fold_stability"] < 0.50][
        ["feature", "family", "fold_stability", "mean_importance", "mean_log_loss_increase"]
    ].copy()
    rejected_unstable_features["rejection_reason"] = "fold_stability_below_0.50"
    rejected_from_subset = pd.DataFrame(all_rejected_feature_rows)
    if len(rejected_from_subset):
        rejected_from_subset = (
            rejected_from_subset.groupby(["feature", "family", "rejection_reason"], as_index=False)
            .agg(n_fold_rejections=("fold", "nunique"))
        )
        rejected_unstable_features = rejected_unstable_features.merge(
            rejected_from_subset[["feature", "n_fold_rejections"]],
            on="feature",
            how="left",
        )
    else:
        rejected_unstable_features["n_fold_rejections"] = np.nan
    evidence_failures: List[str] = []
    if not bool(overall_metrics.get("feature_validation_pass", False)):
        evidence_failures.append("feature_validation_fail")
    if not bool(overall_metrics.get("model_comparison_pass", False)):
        evidence_failures.append("model_comparison_fail")
    overall_metrics["evidence_hierarchy_pass"] = len(evidence_failures) == 0
    overall_metrics["evidence_hierarchy_reason"] = "ok" if overall_metrics["evidence_hierarchy_pass"] else ";".join(evidence_failures)
    overall_metrics["promotion_pass"] = bool(
        overall_metrics.get("robustness_pass", False)
        and overall_metrics.get("portfolio_policy_pass", False)
        and overall_metrics.get("evidence_hierarchy_pass", False)
    )

    # Strategy library and scorecards.
    strategy_scorecards = pd.DataFrame(
        [
            {
                "max_concurrent": int(best_concurrent),
                "scorecard_label": SCORECARD_LABEL,
                "scorecard_archetype": SCORECARD_ARCHETYPE,
                "research_viable": bool(overall_metrics.get("research_viable", False)),
                "live_pilot_viable": bool(overall_metrics.get("live_pilot_viable", False)),
                "allocation_ready": bool(overall_metrics.get("allocation_ready", False)),
                "feature_validation_pass": bool(overall_metrics.get("feature_validation_pass", False)),
                "model_comparison_pass": bool(overall_metrics.get("model_comparison_pass", False)),
                "evidence_hierarchy_pass": bool(overall_metrics.get("evidence_hierarchy_pass", False)),
                "ranking_map_guardrails_pass": bool(overall_metrics.get("ranking_map_guardrails_pass", False)),
                "promotion_pass": bool(overall_metrics.get("promotion_pass", False)),
                "implementation_status": str(overall_metrics.get("implementation_status", "present")),
                "verification_stage_reached": str(overall_metrics.get("verification_stage_reached", "code_present")),
                "schema_version": SCHEMA_VERSION,
                "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
                "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
                "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
                "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
                "trial_scope_formal": TRIAL_SCOPE_FORMAL,
                "trial_count_formal": int(overall_metrics.get("trial_count_formal", threshold_policy_trial_count(config))),
            }
        ]
    )
    strategy_library = pd.DataFrame()
    if len(by_conc):
        strategy_library = by_conc.copy()
        positive_fold_ratio = (
            fold_metrics_df.groupby("max_concurrent")["calmar"]
            .apply(lambda s: float((s > 0).mean()))
            .reset_index(name="positive_fold_ratio")
        )
        strategy_library = strategy_library.merge(positive_fold_ratio, on="max_concurrent", how="left")
        if len(trades_df):
            top_conc_rows: List[Dict[str, Any]] = []
            for max_conc, grp in trades_df.groupby("max_concurrent"):
                per_ticker_conc = grp.groupby("ticker")["pnl"].sum().abs()
                top_share = float(per_ticker_conc.max() / per_ticker_conc.sum()) if per_ticker_conc.sum() > 0 else 1.0
                top_conc_rows.append({"max_concurrent": int(max_conc), "top_ticker_concentration": top_share})
            strategy_library = strategy_library.merge(pd.DataFrame(top_conc_rows), on="max_concurrent", how="left")
        else:
            strategy_library["top_ticker_concentration"] = np.nan
        if all_fold_ic:
            ic_by_conc = (
                pd.DataFrame(all_fold_ic).groupby("max_concurrent", as_index=False)
                .agg(avg_icir=("icir_r_multiple", "mean"), avg_spearman_ic=("spearman_ic_r_multiple", "mean"))
            )
            strategy_library = strategy_library.merge(ic_by_conc, on="max_concurrent", how="left")
        else:
            strategy_library["avg_icir"] = np.nan
            strategy_library["avg_spearman_ic"] = np.nan
        final_strategy_fields = {
            "max_concurrent": int(best_concurrent),
            "best_max_concurrent": int(best_concurrent),
            "stitched_daily_total_return": float(overall_metrics.get("stitched_daily_total_return", np.nan)),
            "stitched_daily_cagr": float(overall_metrics.get("stitched_daily_cagr", np.nan)),
            "stitched_daily_mdd": float(overall_metrics.get("stitched_daily_mdd", np.nan)),
            "stitched_daily_calmar": float(overall_metrics.get("stitched_daily_calmar", np.nan)),
            "adjusted_sharpe_daily": float(overall_metrics.get("adjusted_sharpe_daily", np.nan)),
            "sharpe_daily_raw": float(overall_metrics.get("sharpe_daily_raw", np.nan)),
            "deflated_sharpe_daily": float(overall_metrics.get("deflated_sharpe_daily", np.nan)),
            "deflated_sharpe_probability": float(overall_metrics.get("deflated_sharpe_probability", np.nan)),
            "deflated_sharpe_benchmark": float(overall_metrics.get("deflated_sharpe_benchmark", np.nan)),
            "white_rc_pass_rate": float(overall_metrics.get("white_rc_pass_rate", np.nan)),
            "n_folds": int(overall_metrics.get("n_folds", 0)),
            "n_selected_folds": int(overall_metrics.get("n_selected_folds", 0)),
            "n_skipped_folds": int(overall_metrics.get("n_skipped_folds", 0)),
            "fold_skip_rate": float(overall_metrics.get("fold_skip_rate", np.nan)),
            "capacity_rule_compliant": bool(overall_metrics.get("capacity_rule_compliant", False)),
            "capacity_rule_violations": int(overall_metrics.get("capacity_rule_violations", 0)),
            "avg_participation_rate": float(overall_metrics.get("avg_participation_rate", np.nan)),
            "p95_participation_rate": float(overall_metrics.get("p95_participation_rate", np.nan)),
            "avg_active_positions_daily": float(overall_metrics.get("avg_active_positions_daily", np.nan)),
            "median_active_positions_daily": float(overall_metrics.get("median_active_positions_daily", np.nan)),
            "p95_active_positions_daily": float(overall_metrics.get("p95_active_positions_daily", np.nan)),
            "flat_day_fraction": float(overall_metrics.get("flat_day_fraction", np.nan)),
            "at_cap_day_fraction": float(overall_metrics.get("at_cap_day_fraction", np.nan)),
            "avg_active_exposure_daily": float(overall_metrics.get("avg_active_exposure_daily", np.nan)),
            "regime_diversity_policy_pass": bool(overall_metrics.get("regime_diversity_policy_pass", False)),
            "regime_diversity_policy_reason": str(overall_metrics.get("regime_diversity_policy_reason", "")),
            "top_regime_pnl_share": float(overall_metrics.get("top_regime_pnl_share", np.nan)),
            "top_regime_label": str(overall_metrics.get("top_regime_label", "")),
            "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
            "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
            "trial_scope_formal": TRIAL_SCOPE_FORMAL,
            "trial_count_formal": int(overall_metrics.get("trial_count_formal", threshold_policy_trial_count(config))),
            "robustness_pass": bool(overall_metrics.get("robustness_pass", False)),
            "portfolio_policy_pass": bool(overall_metrics.get("portfolio_policy_pass", False)),
            "promotion_pass": bool(overall_metrics.get("promotion_pass", False)),
            "robustness_reason": str(overall_metrics.get("robustness_reason", "")),
            "portfolio_policy_reason": str(overall_metrics.get("portfolio_policy_reason", "")),
            "feature_validation_pass": bool(overall_metrics.get("feature_validation_pass", False)),
            "model_comparison_pass": bool(overall_metrics.get("model_comparison_pass", False)),
            "evidence_hierarchy_pass": bool(overall_metrics.get("evidence_hierarchy_pass", False)),
            "ranking_map_guardrails_pass": bool(overall_metrics.get("ranking_map_guardrails_pass", False)),
            "ranking_map_guardrail_failure_reasons": str(overall_metrics.get("ranking_map_guardrail_failure_reasons", "")),
            "ranking_map_max_fallback_usage_fraction_allowed": float(
                overall_metrics.get("ranking_map_max_fallback_usage_fraction_allowed", np.nan)
            ),
            "ranking_map_min_adjacent_fold_spearman_allowed": float(
                overall_metrics.get("ranking_map_min_adjacent_fold_spearman_allowed", np.nan)
            ),
            "ranking_map_fallback_usage_fraction_observed_max_threshold_holdout": float(
                overall_metrics.get("ranking_map_fallback_usage_fraction_observed_max_threshold_holdout", np.nan)
            ),
            "ranking_map_fallback_usage_fraction_observed_max_test": float(
                overall_metrics.get("ranking_map_fallback_usage_fraction_observed_max_test", np.nan)
            ),
            "ranking_map_adjacent_fold_spearman_observed_min_threshold_holdout": float(
                overall_metrics.get("ranking_map_adjacent_fold_spearman_observed_min_threshold_holdout", np.nan)
            ),
            "ranking_map_adjacent_fold_spearman_observed_min_test": float(
                overall_metrics.get("ranking_map_adjacent_fold_spearman_observed_min_test", np.nan)
            ),
            "scorecard_label": SCORECARD_LABEL,
            "scorecard_archetype": SCORECARD_ARCHETYPE,
            "research_viable": bool(overall_metrics.get("research_viable", False)),
            "live_pilot_viable": bool(overall_metrics.get("live_pilot_viable", False)),
            "allocation_ready": bool(overall_metrics.get("allocation_ready", False)),
            "implementation_status": str(overall_metrics.get("implementation_status", "present")),
            "verification_stage_reached": str(overall_metrics.get("verification_stage_reached", "code_present")),
            "schema_version": SCHEMA_VERSION,
            "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
            "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
        }
        strategy_library = strategy_library.merge(pd.DataFrame([final_strategy_fields]), on="max_concurrent", how="left")
        strategy_library["hard_gate_pass"] = (
            strategy_library["robustness_pass"].astype(bool)
            & strategy_library["feature_validation_pass"].astype(bool)
            & strategy_library["model_comparison_pass"].astype(bool)
        )
        strategy_library = strategy_library.sort_values(
            ["promotion_pass", "hard_gate_pass", "robustness_pass", "stitched_daily_calmar", "avg_pf", "avg_expectancy_r", "n_trades"],
            ascending=[False, False, False, False, False, False, False],
        ).reset_index(drop=True)
        strategy_library["strategy_rank"] = np.arange(1, len(strategy_library) + 1)

    # Seed robustness: evaluate shortlisted strategy policy across configured seed list.
    seed_list = resolve_seed_list(config)
    seed_rows: List[Dict[str, Any]] = [
        {
            "seed": int(config.random_seed),
            "n_folds": int(overall_metrics.get("n_folds", 0)),
            "n_selected_folds": int(overall_metrics.get("n_selected_folds", 0)),
            "n_trades": float(overall_metrics.get("n_trades", np.nan)),
            "profit_factor": float(overall_metrics.get("profit_factor", np.nan)),
            "calmar": float(overall_metrics.get("stitched_daily_calmar", overall_metrics.get("calmar", np.nan))),
            "expectancy_r": float(overall_metrics.get("expectancy_r", np.nan)),
            "cagr": float(overall_metrics.get("stitched_daily_cagr", overall_metrics.get("cagr", np.nan))),
            "mdd": float(overall_metrics.get("stitched_daily_mdd", overall_metrics.get("mdd", np.nan))),
            "sharpe": float(overall_metrics.get("sharpe", np.nan)),
            "adjusted_sharpe_daily": float(overall_metrics.get("adjusted_sharpe_daily", np.nan)),
            "deflated_sharpe_daily": float(overall_metrics.get("deflated_sharpe_daily", np.nan)),
            "promotion_pass": bool(overall_metrics.get("promotion_pass", False)),
        }
    ]
    extra_seeds = [s for s in seed_list if s != config.random_seed]
    for seed in extra_seeds:
        logging.info(
            "Seed robustness sweep: evaluating seed=%s with max_concurrent=%s",
            seed,
            best_concurrent,
        )
        seed_rows.append(
            evaluate_seed_robustness(
                base_config=config,
                seed=int(seed),
                model_df=model_df,
                folds=folds,
                features=features,
                max_concurrent=best_concurrent,
            )
        )
    per_seed_df = pd.DataFrame(seed_rows).sort_values("seed").reset_index(drop=True)
    summary_row = {
        "row_type": "summary",
        "seed_mode": config.seed_mode,
        "n_seeds_evaluated": int(len(per_seed_df)),
        "seed_list": json.dumps(per_seed_df["seed"].astype(int).tolist()),
        "best_max_concurrent": int(best_concurrent),
        "mean_profit_factor": float(per_seed_df["profit_factor"].mean()),
        "std_profit_factor": float(per_seed_df["profit_factor"].std(ddof=0)),
        "mean_calmar": float(per_seed_df["calmar"].mean()),
        "std_calmar": float(per_seed_df["calmar"].std(ddof=0)),
        "mean_expectancy_r": float(per_seed_df["expectancy_r"].mean()),
        "std_expectancy_r": float(per_seed_df["expectancy_r"].std(ddof=0)),
        "mean_cagr": float(per_seed_df["cagr"].mean()),
        "std_cagr": float(per_seed_df["cagr"].std(ddof=0)),
        "mean_mdd": float(per_seed_df["mdd"].mean()),
        "std_mdd": float(per_seed_df["mdd"].std(ddof=0)),
        "mean_adjusted_sharpe_daily": float(per_seed_df["adjusted_sharpe_daily"].mean()) if "adjusted_sharpe_daily" in per_seed_df.columns else np.nan,
        "mean_deflated_sharpe_daily": float(per_seed_df["deflated_sharpe_daily"].mean()) if "deflated_sharpe_daily" in per_seed_df.columns else np.nan,
        "promotion_pass_rate": float(per_seed_df["promotion_pass"].mean()) if "promotion_pass" in per_seed_df.columns else np.nan,
    }
    per_seed_df.insert(0, "row_type", "per_seed")
    per_seed_df.insert(1, "seed_mode", config.seed_mode)
    seed_robustness_summary = pd.concat(
        [pd.DataFrame([summary_row]), per_seed_df],
        ignore_index=True,
        sort=False,
    )

    # Persist current-state artifacts (overwrite-oriented; atomic for critical files).
    atomic_write_csv(fold_metrics_df, paths.metrics_dir / "fold_metrics.csv")
    if all_fold_ic:
        atomic_write_csv(pd.DataFrame(all_fold_ic), paths.metrics_dir / "fold_ic_summary.csv")
    atomic_write_csv(trades_df, paths.metrics_dir / "trade_blotter.csv")
    atomic_write_csv(equity_df, paths.metrics_dir / "equity_curves.csv")
    atomic_write_csv(pd.DataFrame(all_thresholds), paths.metrics_dir / "selected_thresholds.csv")
    atomic_write_csv(threshold_candidate_df, paths.metrics_dir / "threshold_candidate_diagnostics.csv")
    atomic_write_csv(stitched_policy_daily, paths.metrics_dir / "policy_daily_returns.csv")
    atomic_write_csv(by_conc, paths.metrics_dir / "concurrency_comparison.csv")
    atomic_write_csv(feature_importance_df, paths.features_dir / "feature_importances_by_fold.csv")
    atomic_write_csv(
        pd.concat(all_inner_feature_importance, ignore_index=True) if all_inner_feature_importance else pd.DataFrame(),
        paths.features_dir / "inner_feature_importances_by_fold.csv",
    )
    atomic_write_csv(subset_search_summary, paths.features_dir / "subset_search_summary.csv")
    atomic_write_csv(pd.DataFrame(all_selected_feature_rows), paths.features_dir / "selected_features_by_fold.csv")
    atomic_write_csv(pd.DataFrame(all_rejected_feature_rows), paths.features_dir / "rejected_features_by_fold.csv")
    atomic_write_csv(feature_stability, paths.features_dir / "feature_stability_summary.csv")
    atomic_write_csv(ranked_feature_table, paths.features_dir / "ranked_feature_table.csv")
    atomic_write_csv(feature_validation_rows_df, paths.features_dir / "feature_validation_rows.csv")
    atomic_write_csv(feature_validation_daily_df, paths.features_dir / "feature_validation_ic_daily_rows.csv")
    atomic_write_csv(feature_validation_report, paths.features_dir / "feature_validation_report.csv")
    atomic_write_csv(family_importance_table, paths.features_dir / "family_importance_table.csv")
    atomic_write_csv(fold_stability_table, paths.features_dir / "fold_stability_table.csv")
    atomic_write_csv(feature_ablation, paths.features_dir / "feature_ablation.csv")
    atomic_write_csv(family_ablation, paths.features_dir / "family_ablation.csv")
    atomic_write_csv(selected_final_feature_set, paths.features_dir / "selected_final_feature_set.csv")
    atomic_write_csv(rejected_unstable_features, paths.features_dir / "rejected_unstable_features.csv")
    atomic_write_csv(regime_specific_importance, paths.features_dir / "regime_specific_importance.csv")
    atomic_write_csv(ensemble_importance, paths.features_dir / "ensemble_importance.csv")
    atomic_write_csv(permutation_importance, paths.features_dir / "permutation_importance.csv")
    atomic_write_csv(strategy_library, paths.strategies_dir / "strategy_library.csv")
    atomic_write_csv(strategy_scorecards, paths.strategies_dir / "strategy_scorecards.csv")
    atomic_write_csv(model_comparison_rows_df, paths.strategies_dir / "model_comparison_report_rows.csv")
    atomic_write_csv(model_comparison_report, paths.strategies_dir / "model_comparison_report.csv")
    position_ranking_audit_df = ensure_columns(pd.DataFrame(all_position_ranking_rows), POSITION_RANKING_AUDIT_COLUMNS)
    position_ranking_audit_df["schema_version"] = SCHEMA_VERSION
    position_ranking_audit_df["robustness_method_version"] = ROBUSTNESS_METHOD_VERSION
    position_ranking_audit_df["search_family_definition_version"] = SEARCH_FAMILY_DEFINITION_VERSION
    position_ranking_audit_df["implementation_status"] = config.implementation_status
    position_ranking_audit_df["verification_stage_reached"] = config.verification_stage_reached
    position_ranking_audit_df["threshold_search_corrected"] = THRESHOLD_SEARCH_CORRECTED
    position_ranking_audit_df["full_pipeline_corrected"] = FULL_PIPELINE_CORRECTED
    position_ranking_audit_df["trial_scope_formal"] = TRIAL_SCOPE_FORMAL
    position_ranking_audit_df["trial_count_formal"] = int(threshold_policy_trial_count(config))
    atomic_write_csv(position_ranking_audit_df, paths.strategies_dir / "position_ranking_audit.csv")
    atomic_write_csv(seed_robustness_summary, paths.strategies_dir / "seed_robustness_summary.csv")
    verification["implementation_status"] = overall_metrics.get("implementation_status", config.implementation_status)
    verification["verification_stage_reached"] = overall_metrics.get("verification_stage_reached", config.verification_stage_reached)
    verification["ranking_map_guardrails_pass"] = bool(overall_metrics.get("ranking_map_guardrails_pass", False))
    verification["ranking_map_guardrail_failure_reasons"] = str(
        overall_metrics.get("ranking_map_guardrail_failure_reasons", "")
    )
    atomic_write_json(paths.state_dir / "verification.json", verification)
    atomic_write_json(paths.state_dir / "config_snapshot.json", config_snapshot_payload)
    atomic_write_json(paths.metrics_dir / "overall_metrics.json", overall_metrics)
    best_strategy_summary = (
        strategy_library.iloc[0].to_dict()
        if len(strategy_library)
        else {
            "max_concurrent": best_concurrent,
            "schema_version": SCHEMA_VERSION,
            "robustness_method_version": ROBUSTNESS_METHOD_VERSION,
            "search_family_definition_version": SEARCH_FAMILY_DEFINITION_VERSION,
            "implementation_status": str(overall_metrics.get("implementation_status", "present")),
            "verification_stage_reached": str(overall_metrics.get("verification_stage_reached", "code_present")),
            "threshold_search_corrected": THRESHOLD_SEARCH_CORRECTED,
            "full_pipeline_corrected": FULL_PIPELINE_CORRECTED,
            "trial_scope_formal": TRIAL_SCOPE_FORMAL,
            "trial_count_formal": int(overall_metrics.get("trial_count_formal", threshold_policy_trial_count(config))),
            "feature_validation_pass": bool(overall_metrics.get("feature_validation_pass", False)),
            "model_comparison_pass": bool(overall_metrics.get("model_comparison_pass", False)),
            "evidence_hierarchy_pass": bool(overall_metrics.get("evidence_hierarchy_pass", False)),
            "ranking_map_guardrails_pass": bool(overall_metrics.get("ranking_map_guardrails_pass", False)),
            "ranking_map_guardrail_failure_reasons": str(overall_metrics.get("ranking_map_guardrail_failure_reasons", "")),
            "robustness_pass": bool(overall_metrics.get("robustness_pass", False)),
            "portfolio_policy_pass": bool(overall_metrics.get("portfolio_policy_pass", False)),
            "promotion_pass": bool(overall_metrics.get("promotion_pass", False)),
            "note": "No strategies generated.",
        }
    )
    if isinstance(best_strategy_summary, dict):
        best_strategy_summary.setdefault("dataset_build_id", config_snapshot_payload.get("dataset_build_id"))
        best_strategy_summary.setdefault("export_panel_version_id", config_snapshot_payload.get("export_panel_version_id"))
        best_strategy_summary.setdefault("feature_set_version", config_snapshot_payload.get("feature_set_version"))
    atomic_write_json(paths.strategies_dir / "best_strategy_summary.json", best_strategy_summary)

    plot_source = (
        stitched_policy_daily[["timestamp_utc", "equity"]].copy()
        if len(stitched_policy_daily)
        else equity_best
    )
    plot_equity_curve(plot_source, paths.reports_dir / "equity_curve_best_concurrency.png", "Equity (max concurrent cap = 8)")
    report_md = write_markdown_report(
        paths.reports_dir / "final_report.md",
        output_dir,
        config,
        verification,
        features,
        fold_metrics_df,
        overall_metrics,
        ranked_feature_table if len(ranked_feature_table) else feature_stability,
    )
    maybe_log_mlflow_summary(
        config=config,
        input_path=input_path,
        paths=paths,
        config_snapshot_payload=config_snapshot_payload,
        overall_metrics=overall_metrics,
        fold_metrics_df=fold_metrics_df,
    )
    summary = {
        "verification": verification,
        "best_concurrency": best_concurrent,
        "overall_metrics": overall_metrics,
        "model_ready_rows": int(len(model_df)),
        "features_used": list(features),
        "dataset_build_id": config_snapshot_payload.get("dataset_build_id"),
        "export_panel_version_id": config_snapshot_payload.get("export_panel_version_id"),
        "feature_set_version": config_snapshot_payload.get("feature_set_version"),
        "report_markdown": str(report_md),
        "output_dir": str(output_dir),
    }
    logging.info("Pipeline complete. Summary: %s", summary)
    return summary


def log_overall_summary(metrics: Dict[str, float]) -> None:
    pf = metrics.get("profit_factor", 0.0)
    pf_text = "inf" if pf == float("inf") else f"{float(pf):.2f}"
    logging.info(
        "Overall Metrics Summary (Best Concurrency)\n"
        "Trades: %s\n"
        "Max Concurrent Cap: %s\n"
        "Stitched Daily Return: %.2f%%\n"
        "Stitched Daily CAGR: %.2f%%\n"
        "Stitched Daily Max Drawdown: %.2f%%\n"
        "Stitched Daily Calmar: %.2f\n"
        "Profit Factor: %s\n"
        "Win Rate: %.1f%%\n"
        "Expectancy (R): %.3f\n"
        "Research Score: %.1f\n"
        "Top Ticker Concentration: %.1f%%\n"
        "Adjusted Sharpe Daily: %.2f\n"
        "Deflated Sharpe Daily: %.3f\n"
        "White RC Pass Rate: %.1f%%\n"
        "Robustness Pass: %s | Portfolio Policy Pass: %s | Promotion Pass: %s",
        metrics.get("n_trades", 0),
        metrics.get("best_max_concurrent", 0),
        metrics.get("stitched_daily_total_return", metrics.get("total_return", 0.0)) * 100,
        metrics.get("stitched_daily_cagr", metrics.get("cagr", 0.0)) * 100,
        metrics.get("stitched_daily_mdd", metrics.get("mdd", 0.0)) * 100,
        metrics.get("stitched_daily_calmar", metrics.get("calmar", 0.0)),
        pf_text,
        metrics.get("win_rate", 0.0) * 100,
        metrics.get("expectancy_r", 0.0),
        metrics.get("research_score", 0.0),
        metrics.get("top_ticker_share_abs", 0.0) * 100,
        metrics.get("adjusted_sharpe_daily", 0.0),
        metrics.get("deflated_sharpe_daily", 0.0),
        metrics.get("white_rc_pass_rate", 0.0) * 100,
        metrics.get("robustness_pass", False),
        metrics.get("portfolio_policy_pass", False),
        metrics.get("promotion_pass", False),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Beginning-to-end swing-trading research pipeline")
    parser.add_argument("--input_panel_csv", required=True, help="Path to the cleaned panel CSV")
    parser.add_argument("--output_dir", required=True, help="Directory for all outputs")
    parser.add_argument("--include_physics_block", action="store_true", help="Include the physics/regime feature block")
    parser.add_argument("--no_physics_block", action="store_false", dest="include_physics_block", help="Exclude the physics/regime feature block")
    parser.set_defaults(include_physics_block=True)
    parser.add_argument("--starting_capital", type=float, default=50_000.0)
    parser.add_argument("--risk_per_trade", type=float, default=0.03)
    parser.add_argument("--resume", action="store_true", help="Resume from last completed fold (requires same input and output_dir)")
    parser.add_argument("--enable_optuna_tuning", action="store_true", help="Enable Optuna hyperparameter tuning (run baseline first, then enable only if baseline_passed)")
    parser.add_argument("--bars_per_year", type=float, default=252 * 6.5, help="Bar frequency for Sharpe annualization (e.g. 252*6.5 for hourly US equity)")
    parser.add_argument("--outer_train_months", type=int, default=36, help="Initial outer-train span in months")
    parser.add_argument("--outer_test_months", type=int, default=6, help="Outer-test span in months")
    parser.add_argument("--inner_folds", type=int, default=5, help="Number of purged inner CV folds")
    parser.add_argument("--threshold_holdout_months", type=int, default=3, help="Calendar months of purged train used as threshold holdout")
    parser.add_argument("--calibration_holdout_months", type=int, default=2, help="Calendar months of purged fit reserved for out-of-sample probability calibration")
    parser.add_argument("--random_seed", type=int, default=42, help="Primary random seed for model reproducibility")
    parser.add_argument("--seed_mode", choices=["single", "research", "final"], default="single", help="Seed robustness mode")
    parser.add_argument("--n_jobs_tree_models", type=int, default=-1, help="Parallelism for RF/ET/LGBM models")
    parser.add_argument("--n_jobs_xgb", type=int, default=8, help="Parallelism for XGBoost")
    parser.add_argument("--deterministic_mode", action="store_true", help="Force single-thread canonical reproducibility mode")
    parser.add_argument(
        "--implementation_status",
        choices=list(IMPLEMENTATION_STATUS_VALUES),
        default="present",
        help="Current implementation/verification status label to stamp into major artifacts",
    )
    parser.add_argument(
        "--verification_stage_reached",
        default="code_present",
        help="Free-text verification stage label to stamp into major artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = PipelineConfig(
        input_panel_csv=args.input_panel_csv,
        output_dir=args.output_dir,
        resume=bool(args.resume),
        include_physics_block=bool(args.include_physics_block),
        starting_capital=float(args.starting_capital),
        risk_per_trade=float(args.risk_per_trade),
        use_optuna_tuning=bool(args.enable_optuna_tuning),
        bars_per_year=float(getattr(args, "bars_per_year", 252 * 6.5)),
        outer_train_months=int(getattr(args, "outer_train_months", 36)),
        outer_test_months=int(getattr(args, "outer_test_months", 6)),
        inner_folds=int(getattr(args, "inner_folds", 5)),
        threshold_holdout_months=int(getattr(args, "threshold_holdout_months", 3)),
        calibration_holdout_months=int(getattr(args, "calibration_holdout_months", 2)),
        random_seed=int(getattr(args, "random_seed", 42)),
        seed_mode=str(getattr(args, "seed_mode", "single")),
        n_jobs_tree_models=int(getattr(args, "n_jobs_tree_models", -1)),
        n_jobs_xgb=int(getattr(args, "n_jobs_xgb", 8)),
        deterministic_mode=bool(getattr(args, "deterministic_mode", False)),
        implementation_status=str(getattr(args, "implementation_status", "present")),
        verification_stage_reached=str(getattr(args, "verification_stage_reached", "code_present")),
    )
    run_pipeline_with_optional_lineage(config)


if __name__ == "__main__":
    main()
