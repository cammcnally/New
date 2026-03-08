#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import math
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from xgboost import XGBClassifier

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

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
    max_concurrent_options: Tuple[int, ...] = (5, 7, 10)
    max_positions_per_ticker: int = 2
    slippage_per_fill: float = 0.0001
    overnight_brokerage: float = 0.0003
    # Label geometry
    atr_length: int = 14
    stop_atr_multiple: float = 1.0
    target_atr_multiple: float = 2.0
    max_horizon_bars: int = 105
    long_only_primary_book: bool = True
    # Walk-forward / CV
    outer_train_months: int = 36
    outer_test_months: int = 6
    inner_folds: int = 5
    embargo_bars: int = 35
    # Threshold search
    p_min_grid: Tuple[float, ...] = (0.40, 0.43, 0.46, 0.49, 0.52, 0.55, 0.58, 0.61, 0.64)
    theta_ev_grid: Tuple[float, ...] = (0.10, 0.15, 0.20, 0.25)
    theta_rel_grid: Tuple[float, ...] = (1.05, 1.10, 1.15)
    estimated_overnights_for_ranking: int = 3
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
    # Meta model and calibration
    meta_c: float = 0.1
    calibrator_c: float = 1.0
    # Features
    include_physics_block: bool = True
    max_missing_feature_fraction: float = 0.35
    # Reproducibility / runtime
    random_seed: int = 42
    n_jobs_tree_models: int = -1
    n_jobs_xgb: int = 8
    max_folds: Optional[int] = None
    # Tuning (Optuna, optional). Run baseline first; enable only after baseline_passed().
    use_optuna_tuning: bool = False
    optuna_n_trials: int = 20
    require_baseline_pass_for_tuning: bool = True


CORE_FEATURES: List[str] = [
    "ret_1", "ret_3", "ret_5", "ret_10", "ret_20",
    "rsi_14", "stoch_k_14_3", "stoch_d_14_3",
    "macd_12_26_9", "macd_signal_12_26_9", "macd_hist_12_26_9",
    "roc_10", "roc_20", "adx_14", "plus_di_14", "minus_di_14",
    "ema_gap_10_20", "ema_gap_20_50", "price_vs_ema20", "price_vs_ema50",
    "atr_14", "atr_pct_14", "bb_pos_20_2", "bb_width_20_2", "donchian_pos_20",
    "range_pct_1", "realized_vol_10", "realized_vol_20", "vol_of_vol_20",
    "vol_z_20", "rel_volume_20", "obv", "obv_slope_5", "cmf_20", "mfi_14",
    "xs_ret_5_z", "xs_ret_20_z", "xs_rsi_14_z", "xs_atr_pct_14_z", "xs_rel_volume_20_z",
]
PHYSICS_FEATURES: List[str] = [
    "hurst_proxy_50", "entropy_sign_20", "autocorr_1_20", "autocorr_5_20", "fracret_0_35"
]

# ============================================================
# UTILITIES
# ============================================================
def setup_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(output_dir / "pipeline.log", mode="w"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def clip_prob(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    return np.clip(p, 1e-6, 1 - 1e-6)


def logit(p: np.ndarray) -> np.ndarray:
    p = clip_prob(p)
    return np.log(p / (1.0 - p))


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
def add_per_ticker_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy().reset_index(drop=True)
    c = g["close"].astype(float)
    h = g["high"].astype(float)
    l = g["low"].astype(float)
    o = g["open"].astype(float)
    v = g["volume"].astype(float)
    ret1 = c.pct_change()
    g["ret_1"] = ret1
    for n in (3, 5, 10, 20):
        g[f"ret_{n}"] = c.pct_change(n)
    g["roc_10"] = c.pct_change(10)
    g["roc_20"] = c.pct_change(20)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    g["ema_gap_10_20"] = ema10 / ema20 - 1
    g["ema_gap_20_50"] = ema20 / ema50 - 1
    g["price_vs_ema20"] = c / ema20 - 1
    g["price_vs_ema50"] = c / ema50 - 1
    delta = c.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / 14, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / 14, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    g["rsi_14"] = 100 - (100 / (1 + rs))
    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    k = ((c - low14) / (high14 - low14).replace(0, np.nan)) * 100
    g["stoch_k_14_3"] = k.rolling(3).mean()
    g["stoch_d_14_3"] = g["stoch_k_14_3"].rolling(3).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    g["macd_12_26_9"] = macd
    g["macd_signal_12_26_9"] = signal
    g["macd_hist_12_26_9"] = macd - signal
    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - l).abs(), (h - prev_close).abs(), (l - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    g["atr_14"] = atr
    g["atr_pct_14"] = atr / c.replace(0, np.nan)
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
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    g["bb_pos_20_2"] = (c - lower) / (upper - lower).replace(0, np.nan)
    g["bb_width_20_2"] = (upper - lower) / sma20.replace(0, np.nan)
    d_hi = h.rolling(20).max()
    d_lo = l.rolling(20).min()
    g["donchian_pos_20"] = (c - d_lo) / (d_hi - d_lo).replace(0, np.nan)
    g["range_pct_1"] = (h - l) / c.replace(0, np.nan)
    g["realized_vol_10"] = ret1.rolling(10).std()
    g["realized_vol_20"] = ret1.rolling(20).std()
    g["vol_of_vol_20"] = g["realized_vol_10"].rolling(20).std()
    vol_mean20 = v.rolling(20).mean()
    vol_std20 = v.rolling(20).std()
    g["vol_z_20"] = (v - vol_mean20) / vol_std20.replace(0, np.nan)
    g["rel_volume_20"] = v / vol_mean20.replace(0, np.nan)
    obv = (np.sign(c.diff().fillna(0)) * v).fillna(0).cumsum()
    g["obv"] = obv
    g["obv_slope_5"] = obv.diff(5) / 5
    mfv = (((c - l) - (h - c)) / (h - l).replace(0, np.nan)) * v
    g["cmf_20"] = mfv.rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    tp = (h + l + c) / 3
    rmf = tp * v
    tp_diff = tp.diff()
    pos_mf = rmf.where(tp_diff > 0, 0.0)
    neg_mf = rmf.where(tp_diff < 0, 0.0).abs()
    mfr = pos_mf.rolling(14).sum() / neg_mf.rolling(14).sum().replace(0, np.nan)
    g["mfi_14"] = 100 - (100 / (1 + mfr))
    vr = variance_ratio(c, lag=5, window=50)
    g["hurst_proxy_50"] = 0.5 * (1 + np.log(vr) / np.log(5))
    pos_frac = ret1.gt(0).astype(float).rolling(20).mean()
    g["entropy_sign_20"] = binary_entropy(pos_frac)
    g["autocorr_1_20"] = ret1.rolling(20).corr(ret1.shift(1))
    g["autocorr_5_20"] = ret1.rolling(20).corr(ret1.shift(5))
    g["fracret_0_35"] = fracret(ret1)
    g["next_open"] = o.shift(-1)
    return g


def build_feature_matrix(
    panel: pd.DataFrame, config: PipelineConfig
) -> Tuple[pd.DataFrame, List[str]]:
    pieces = [add_per_ticker_features(g) for _, g in panel.groupby("ticker", sort=False)]
    df = pd.concat(pieces, ignore_index=True).sort_values(["timestamp_utc", "ticker"]).reset_index(drop=True)
    xs_cols = ["ret_5", "ret_20", "rsi_14", "atr_pct_14", "rel_volume_20"]
    for col in xs_cols:
        mean = df.groupby("timestamp_utc")[col].transform("mean")
        std = df.groupby("timestamp_utc")[col].transform("std").replace(0, np.nan)
        df[f"xs_{col}_z"] = (df[col] - mean) / std
    features = CORE_FEATURES + (PHYSICS_FEATURES if config.include_physics_block else [])
    df[list(features)] = df[list(features)].astype(np.float32)
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
        atr = g["atr_14"].values.astype(float)
        ts = pd.to_datetime(g["timestamp_utc"]).values
        long_win = np.full(n, np.nan)
        event_end_idx = np.full(n, np.nan)
        event_end_time = np.array([np.datetime64("NaT")] * n, dtype="datetime64[ns]")
        entry_open = np.full(n, np.nan)
        stop_price = np.full(n, np.nan)
        target_price = np.full(n, np.nan)
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
            for j in range(i + 1, min(n, i + config.max_horizon_bars + 1)):
                hit_stop = l[j] <= stop
                hit_target = h[j] >= target
                if hit_stop and hit_target:
                    outcome = 0
                    end_idx = j
                    break
                if hit_stop:
                    outcome = 0
                    end_idx = j
                    break
                if hit_target:
                    outcome = 1
                    end_idx = j
                    break
            long_win[i] = outcome
            event_end_idx[i] = end_idx
            event_end_time[i] = ts[int(end_idx)]
        g["long_win"] = long_win
        g["event_end_idx"] = event_end_idx
        g["event_end_time"] = pd.to_datetime(event_end_time, utc=True)
        g["entry_open_next"] = entry_open
        g["stop_price"] = stop_price
        g["target_price"] = target_price
        labeled.append(g)
    out = pd.concat(labeled, ignore_index=True)
    out = out.dropna(subset=["long_win"]).copy()
    return out


# ============================================================
# WALK-FORWARD / PURGING
# ============================================================
def build_outer_folds(
    df: pd.DataFrame, config: PipelineConfig
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
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


# ============================================================
# MODELS / STACKING / CALIBRATION
# ============================================================
def make_models(
    config: PipelineConfig,
    pos_weight: float,
    rf_params: Optional[Dict[str, object]] = None,
    et_params: Optional[Dict[str, object]] = None,
    xgb_params: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
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
    }
    if xgb_params:
        _xgb.update(xgb_params)
    xgb = XGBClassifier(**_xgb)
    return {"RF": rf, "ET": et, "XGB": xgb}


def run_optuna_inner(
    train_df: pd.DataFrame,
    config: PipelineConfig,
    features: Sequence[str],
) -> Dict[str, Dict[str, object]]:
    """Run Optuna over inner CV for RF, ET, XGB. Optimizes mean purged-inner-fold log loss. Returns best params per model."""
    if not OPTUNA_AVAILABLE:
        logging.warning("Optuna not available. Using default parameters.")
        return {}

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

    def objective_rf(trial: object) -> float:
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

    def objective_et(trial: object) -> float:
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

    def objective_xgb(trial: object) -> float:
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
            )
        )

    best_params: Dict[str, Dict[str, object]] = {}
    logging.info("  Optuna RF (n_trials=%s)...", config.optuna_n_trials)
    study_rf = optuna.create_study(direction="minimize")
    study_rf.optimize(objective_rf, n_trials=config.optuna_n_trials, show_progress_bar=False)
    best_params["RF"] = study_rf.best_params
    logging.info("  Optuna ET (n_trials=%s)...", config.optuna_n_trials)
    study_et = optuna.create_study(direction="minimize")
    study_et.optimize(objective_et, n_trials=config.optuna_n_trials, show_progress_bar=False)
    best_params["ET"] = study_et.best_params
    logging.info("  Optuna XGB (n_trials=%s)...", config.optuna_n_trials)
    study_xgb = optuna.create_study(direction="minimize")
    study_xgb.optimize(objective_xgb, n_trials=config.optuna_n_trials, show_progress_bar=False)
    best_params["XGB"] = study_xgb.best_params
    logging.info("Optuna best params | %s", best_params)
    return best_params


def impute_fit_transform(
    X_train: pd.DataFrame, X_pred: pd.DataFrame
) -> Tuple[np.ndarray, np.ndarray, SimpleImputer]:
    imp = SimpleImputer(strategy="median")
    return imp.fit_transform(X_train), imp.transform(X_pred), imp


def fit_outer_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    features: Sequence[str],
    config: PipelineConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inner_splits = purged_splits(train_df, config)
    best_params: Dict[str, Dict[str, object]] = {}
    if config.use_optuna_tuning:
        if OPTUNA_AVAILABLE:
            best_params = run_optuna_inner(train_df, config, features)
        else:
            logging.warning("Optuna not installed. Skipping tuning.")
    best_rf = best_params.get("RF", {})
    best_et = best_params.get("ET", {})
    best_xgb = best_params.get("XGB", {})
    # Same best_params are used for OOF base models and full-train base models when Optuna is enabled.
    oof_base = pd.DataFrame(index=train_df.index, columns=["RF", "ET", "XGB"], dtype=float)
    inner_feature_importance: List[Dict[str, object]] = []
    for fold_i, (train_mask, val_mask, span) in enumerate(inner_splits, start=1):
        tr = train_df.loc[train_mask]
        val = train_df.loc[val_mask]
        X_tr_raw = tr[list(features)]
        X_val_raw = val[list(features)]
        y_tr = tr["long_win"].astype(int).values
        pos_weight = max((y_tr == 0).sum() / max((y_tr == 1).sum(), 1), 1.0)
        X_tr, X_val, _ = impute_fit_transform(X_tr_raw, X_val_raw)
        models = make_models(config, pos_weight, rf_params=best_rf, et_params=best_et, xgb_params=best_xgb)
        logging.info(
            "Inner fold %s | train=%s | val=%s | span=%s -> %s",
            fold_i, len(tr), len(val), span[0], span[1],
        )
        for name, model in models.items():
            model.fit(X_tr, y_tr)
            oof_base.loc[val.index, name] = model.predict_proba(X_val)[:, 1]
            if hasattr(model, "feature_importances_"):
                for feat, imp in zip(features, model.feature_importances_):
                    inner_feature_importance.append(
                        {"fold": fold_i, "model": name, "feature": feat, "importance": float(imp)}
                    )
    valid_idx = oof_base.dropna().index
    meta_input = oof_base.loc[valid_idx].values
    y_meta = train_df.loc[valid_idx, "long_win"].astype(int).values
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
    calibrator.fit(logit(oof_meta_raw).reshape(-1, 1), y_meta)
    oof_meta_cal = calibrator.predict_proba(logit(oof_meta_raw).reshape(-1, 1))[:, 1]
    train_scored = train_df.loc[valid_idx].copy()
    train_scored["p_cal"] = oof_meta_cal
    train_scored["cost_est_r"] = estimate_cost_r_from_frame(train_scored, config)
    X_train_raw = train_df[list(features)]
    X_test_raw = test_df[list(features)]
    y_train_full = train_df["long_win"].astype(int).values
    pos_weight = max((y_train_full == 0).sum() / max((y_train_full == 1).sum(), 1), 1.0)
    X_train_full, X_test_full, _ = impute_fit_transform(X_train_raw, X_test_raw)
    full_models = make_models(config, pos_weight, rf_params=best_rf, et_params=best_et, xgb_params=best_xgb)
    full_feature_importance: List[Dict[str, object]] = []
    test_base: Dict[str, np.ndarray] = {}
    for name, model in full_models.items():
        logging.info("Fit full outer model %s | train=%s | test=%s", name, len(train_df), len(test_df))
        model.fit(X_train_full, y_train_full)
        test_base[name] = model.predict_proba(X_test_full)[:, 1]
        if hasattr(model, "feature_importances_"):
            for feat, imp in zip(features, model.feature_importances_):
                full_feature_importance.append(
                    {"model": name, "feature": feat, "importance": float(imp)}
                )
    raw_test_meta = meta.predict_proba(
        np.column_stack([test_base["RF"], test_base["ET"], test_base["XGB"]])
    )[:, 1]
    test_cal = calibrator.predict_proba(logit(raw_test_meta).reshape(-1, 1))[:, 1]
    test_scored = test_df.copy()
    test_scored["p_cal"] = test_cal
    test_scored["cost_est_r"] = estimate_cost_r_from_frame(test_scored, config)
    inner_importance_df = pd.DataFrame(inner_feature_importance)
    full_importance_df = pd.DataFrame(full_feature_importance)
    return train_scored, test_scored, inner_importance_df, full_importance_df


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
    estimated_cost_r: float
    entry_row_idx: int


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


def compute_metrics(trades_df: pd.DataFrame, equity_df: pd.DataFrame) -> Dict[str, float]:
    if len(equity_df) == 0:
        return {
            "n_trades": 0,
            "total_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "calmar": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "avg_hold_hours": 0.0,
            "ending_equity": 0.0,
            "sharpe": 0.0,
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
        periods_per_year = 252 * 6.5
        sharpe = float(period_returns.mean() / period_returns.std() * np.sqrt(periods_per_year))
    else:
        sharpe = 0.0
    if len(trades_df):
        gross_profit = float(trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum())
        gross_loss = float(-trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        win_rate = float((trades_df["pnl"] > 0).mean())
        expectancy_r = float(trades_df["r_multiple"].mean())
        avg_hold_hours = float(
            (pd.to_datetime(trades_df["exit_time"]) - pd.to_datetime(trades_df["entry_time"])).dt.total_seconds().mean() / 3600
        )
    else:
        profit_factor = 0.0
        win_rate = 0.0
        expectancy_r = 0.0
        avg_hold_hours = 0.0
    return {
        "n_trades": int(len(trades_df)),
        "total_return": total_return,
        "cagr": float(cagr),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "profit_factor": float(profit_factor),
        "win_rate": float(win_rate),
        "expectancy_r": float(expectancy_r),
        "avg_hold_hours": float(avg_hold_hours),
        "ending_equity": float(eq.iloc[-1]),
        "sharpe": float(sharpe),
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
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    df = make_session_codes(scored_df).sort_values(["timestamp_utc", "ticker"]).copy()
    by_timestamp = {ts: g.copy() for ts, g in df.groupby("timestamp_utc", sort=True)}
    timestamps = sorted(by_timestamp.keys())
    cash = config.starting_capital
    active: Dict[str, List[Position]] = defaultdict(list)
    pending: List[Dict[str, object]] = []
    trades: List[Dict[str, object]] = []
    equity_curve: List[Dict[str, object]] = []
    replacement_exits = 0

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

        # Carry orders that cannot be filled this bar (no row, at capacity, or at per-ticker slot limit).
        next_pending: List[Dict[str, object]] = []
        for order in pending:
            ticker = str(order["ticker"])
            row_match = group[group["ticker"] == ticker]
            if row_match.empty:
                next_pending.append(order)
                continue
            if total_active_positions() >= max_concurrent:
                next_pending.append(order)
                continue
            if ticker_open_slots(ticker) >= config.max_positions_per_ticker:
                next_pending.append(order)
                continue
            row = row_match.iloc[0]
            entry = float(row["open"])
            atr = float(row["atr_14"])
            if not (np.isfinite(entry) and np.isfinite(atr) and entry > 0 and atr > 0):
                continue
            sizing_equity = float(order.get("sizing_equity", config.starting_capital))
            risk_budget = config.risk_per_trade * max(sizing_equity, 0.0)
            risk_per_share = config.stop_atr_multiple * atr
            if risk_per_share <= 0:
                continue
            shares = int(math.floor(risk_budget / risk_per_share))
            affordable = int(math.floor(cash / (entry * (1 + config.slippage_per_fill)))) if entry > 0 else 0
            shares = max(0, min(shares, affordable))
            if shares <= 0:
                continue
            exec_px = entry * (1 + config.slippage_per_fill)
            cash -= shares * exec_px
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
                    entry_session_code=int(row["session_code"]),
                    p_entry=float(order["p_cal"]),
                    estimated_cost_r=float(order["cost_est_r"]),
                    entry_row_idx=int(row["ticker_row_idx"]),
                )
            )
        pending = next_pending

        for _, row in group.iterrows():
            ticker = row["ticker"]
            if ticker not in active or not active[ticker]:
                continue
            survivors: List[Position] = []
            low = float(row["low"])
            high = float(row["high"])
            close = float(row["close"])
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
                entry_notional = pos.entry_exec_price * pos.shares
                overnights = max(0, int(row["session_code"]) - pos.entry_session_code)
                carry = entry_notional * config.overnight_brokerage * overnights
                proceeds = pos.shares * exit_px - carry
                cash += proceeds
                pnl = proceeds - entry_notional
                denom = (pos.entry_reference_price - pos.stop_price) * pos.shares
                r_multiple = pnl / denom if denom > 0 else np.nan
                trades.append({
                    "fold": fold_name,
                    "ticker": ticker,
                    "entry_time": pos.entry_execution_time,
                    "exit_time": ts,
                    "entry_price": pos.entry_exec_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "reason": reason,
                    "p_entry": pos.p_entry,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "overnights": overnights,
                    "replacement_exit": 0,
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
            p = float(row["p_cal"])
            if not np.isfinite(p) or p < p_min:
                continue
            atr = float(row["atr_14"])
            entry = float(row["entry_open_next"])
            cost_r = float(row["cost_est_r"])
            if not (np.isfinite(atr) and atr > 0 and np.isfinite(entry) and entry > 0 and np.isfinite(cost_r)):
                continue
            ev_r = p * reward_r - (1.0 - p) - cost_r
            if ev_r <= 0:
                continue
            candidates.append({"ticker": ticker, "row": row.to_dict(), "ev_r": float(ev_r), "p": p})
        candidates.sort(key=lambda x: (x["ev_r"], x["p"]), reverse=True)

        for cand in candidates:
            ticker = cand["ticker"]
            if ticker_open_slots(ticker) >= config.max_positions_per_ticker:
                continue
            if total_open_slots() < max_concurrent:
                pending.append({**cand["row"], "sizing_equity": current_equity})
                continue
            incumbent_scores: List[Tuple[str, int, float]] = []
            for inc_ticker, positions in active.items():
                row_match = group[group["ticker"] == inc_ticker]
                if row_match.empty:
                    continue
                inc_row = row_match.iloc[0]
                close_inc = float(inc_row["close"])
                p_now_raw = float(inc_row["p_cal"])
                p_now = p_now_raw if np.isfinite(p_now_raw) else positions[0].p_entry
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
            if cand["ev_r"] > weakest_ev_r + theta_ev and cand["ev_r"] > theta_rel * weakest_ev_r:
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
                trades.append({
                    "fold": fold_name,
                    "ticker": weakest_ticker,
                    "entry_time": pos.entry_execution_time,
                    "exit_time": ts,
                    "entry_price": pos.entry_exec_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "reason": "replacement",
                    "p_entry": pos.p_entry,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "overnights": overnights,
                    "replacement_exit": 1,
                })
                replacement_exits += 1
                if total_open_slots() < max_concurrent and ticker_open_slots(ticker) < config.max_positions_per_ticker:
                    pending.append({**cand["row"], "sizing_equity": current_equity})

        equity_curve.append({"timestamp_utc": ts, "equity": mark_equity(group)})

    if timestamps:
        final_ts = timestamps[-1]
        group = by_timestamp[final_ts]
        for ticker, positions in list(active.items()):
            row = group[group["ticker"] == ticker].iloc[0]
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
                trades.append({
                    "fold": fold_name,
                    "ticker": ticker,
                    "entry_time": pos.entry_execution_time,
                    "exit_time": final_ts,
                    "entry_price": pos.entry_exec_price,
                    "exit_price": exit_px,
                    "shares": pos.shares,
                    "reason": "forced_end",
                    "p_entry": pos.p_entry,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "overnights": overnights,
                    "replacement_exit": 0,
                })
            del active[ticker]
        equity_curve.append({"timestamp_utc": final_ts, "equity": cash})

    trades_df = pd.DataFrame(trades)
    equity_df = (
        pd.DataFrame(equity_curve)
        .drop_duplicates(subset=["timestamp_utc"], keep="last")
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )
    metrics = compute_metrics(trades_df, equity_df)
    metrics["replacement_exits"] = int(replacement_exits)
    metrics["total_exits"] = int(len(trades_df))
    metrics["churn"] = float(replacement_exits / max(len(trades_df), 1))
    return trades_df, equity_df, metrics


# ============================================================
# THRESHOLD SELECTION
# ============================================================
def choose_thresholds(
    train_scored: pd.DataFrame,
    config: PipelineConfig,
    fold_name: str,
    max_concurrent: int,
) -> Dict[str, float]:
    best_score = -np.inf
    best_bundle: Optional[Dict[str, float]] = None
    for p_min in config.p_min_grid:
        for theta_ev in config.theta_ev_grid:
            for theta_rel in config.theta_rel_grid:
                trades, equity, metrics = simulate_book(
                    train_scored,
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
                bundle = {
                    "p_min": float(p_min),
                    "theta_ev": float(theta_ev),
                    "theta_rel": float(theta_rel),
                    "score": float(score),
                    **metrics,
                    **meta,
                }
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
    return best_bundle


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


def write_markdown_report(
    output_dir: Path,
    config: PipelineConfig,
    verification: Dict[str, object],
    feature_list: Sequence[str],
    fold_metrics: pd.DataFrame,
    overall_summary: Dict[str, object],
    feature_importance: pd.DataFrame,
) -> Path:
    report_path = output_dir / "final_report.md"
    lines: List[str] = []
    lines.append("# Final Swing Pipeline Report")
    lines.append("")
    lines.append("## 1. Scope")
    lines.append("")
    lines.append("This report summarizes the completed walk-forward, purged/embargoed, probability-calibrated swing pipeline.")
    lines.append("")
    lines.append("## 2. Verified Input Panel")
    lines.append("")
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
    lines.append("## 7. Top Feature Importances")
    lines.append("")
    if len(feature_importance):
        try:
            lines.append(feature_importance.head(25).to_markdown(index=False))
        except Exception:
            lines.append(feature_importance.head(25).to_string())
    else:
        lines.append("No feature importances available.")
    lines.append("")
    lines.append("## 8. Output Directory")
    lines.append("")
    lines.append(f"All CSV / JSON / chart outputs were written to `{output_dir}`.")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ============================================================
# BASELINE GATING (for Optuna)
# ============================================================
def baseline_passed(fold_metrics_df: pd.DataFrame) -> bool:
    """True if a majority of folds beat the base-rate benchmark on log_loss and brier. Use before enabling Optuna."""
    if len(fold_metrics_df) == 0:
        return False
    required_cols = {"test_log_loss", "test_brier", "benchmark_log_loss", "benchmark_brier"}
    if not required_cols.issubset(fold_metrics_df.columns):
        return False
    logloss_pass = (fold_metrics_df["test_log_loss"] < fold_metrics_df["benchmark_log_loss"]).mean()
    brier_pass = (fold_metrics_df["test_brier"] < fold_metrics_df["benchmark_brier"]).mean()
    return (logloss_pass >= 0.60) and (brier_pass >= 0.60)


# ============================================================
# MAIN DRIVER
# ============================================================
def run_pipeline(config: PipelineConfig) -> Dict[str, object]:
    output_dir = Path(config.output_dir)
    setup_logging(output_dir)
    logging.info("Loading panel from %s", config.input_panel_csv)
    panel = load_panel(config)
    verification = verify_panel(panel)
    logging.info("Panel verification: %s", verification)
    enriched, features = build_feature_matrix(panel, config)
    labeled = label_long_events(enriched, config)
    labeled = labeled[~labeled["is_incomplete_session"].astype(bool)].copy()
    labeled["missing_feature_fraction"] = labeled[list(features)].isna().mean(axis=1)
    model_df = labeled[labeled["missing_feature_fraction"] <= config.max_missing_feature_fraction].copy()
    model_path = output_dir / "model_ready_dataset.csv"
    model_df.to_csv(model_path, index=False)
    logging.info("Model-ready dataset written to %s (%s rows)", model_path, len(model_df))
    folds = build_outer_folds(model_df, config)
    if config.max_folds is not None:
        folds = folds[: config.max_folds]
        logging.info("Limited to first %s folds (--max_folds)", len(folds))
    n_folds = len(folds)
    logging.info("Built %s outer folds", n_folds)
    resume_path = output_dir / "resume_state.json"
    all_trades: List[pd.DataFrame] = []
    all_equity: List[pd.DataFrame] = []
    all_fold_metrics: List[Dict[str, object]] = []
    all_feature_importance: List[pd.DataFrame] = []
    all_thresholds: List[Dict[str, object]] = []
    completed_fold_names: List[str] = []
    if config.resume and resume_path.exists():
        try:
            state = json.loads(resume_path.read_text(encoding="utf-8"))
            if state.get("input_panel_csv") == config.input_panel_csv and state.get("include_physics_block") == config.include_physics_block:
                completed_fold_names = state.get("completed_fold_names", [])
                logging.info("Resume: found %s completed folds: %s", len(completed_fold_names), completed_fold_names)
                fm_path = output_dir / "fold_metrics.csv"
                if fm_path.exists() and completed_fold_names:
                    fm = pd.read_csv(fm_path)
                    all_fold_metrics = fm.to_dict("records")
                tb_path = output_dir / "trade_blotter.csv"
                if tb_path.exists() and completed_fold_names:
                    all_trades = [pd.read_csv(tb_path)]
                eq_path = output_dir / "equity_curves.csv"
                if eq_path.exists() and completed_fold_names:
                    all_equity = [pd.read_csv(eq_path)]
                fi_path = output_dir / "feature_importances_by_fold.csv"
                if fi_path.exists() and completed_fold_names:
                    all_feature_importance = [pd.read_csv(fi_path)]
                th_path = output_dir / "selected_thresholds.csv"
                if th_path.exists() and completed_fold_names:
                    all_thresholds = pd.read_csv(th_path).to_dict("records")
            else:
                logging.info("Resume: config mismatch, starting fresh")
        except Exception as e:
            logging.warning("Resume: failed to load state: %s", e)
    for fold_num, (_, train_end, test_start, test_end) in enumerate(folds, start=1):
        fold_name = f"fold_{fold_num:02d}"
        if fold_name in completed_fold_names:
            logging.info("Resume: skipping already completed %s", fold_name)
            continue
        logging.info("[%s / %s] === %s | train<%s | test[%s .. %s) ===", fold_num, n_folds, fold_name, train_end, test_start, test_end)
        train_df = model_df[model_df["timestamp_utc"] < train_end].copy()
        test_df = model_df[(model_df["timestamp_utc"] >= test_start) & (model_df["timestamp_utc"] < test_end)].copy()
        if len(train_df) == 0 or len(test_df) == 0:
            logging.info("Skipping %s due to empty train/test split", fold_name)
            continue
        train_scored, test_scored, inner_imp, full_imp = fit_outer_fold(train_df, test_df, features, config)
        train_diag = classification_diagnostics(train_scored["long_win"], train_scored["p_cal"])
        test_diag = classification_diagnostics(test_scored["long_win"], test_scored["p_cal"])
        bench_diag = benchmark_base_rate_metrics(test_scored["long_win"], train_df["long_win"])
        if len(full_imp):
            full_imp_copy = full_imp.copy()
            full_imp_copy["fold"] = fold_name
            all_feature_importance.append(full_imp_copy)
        for max_concurrent in config.max_concurrent_options:
            thresholds = choose_thresholds(train_scored, config, fold_name, max_concurrent)
            all_thresholds.append({
                "fold": fold_name,
                "max_concurrent": max_concurrent,
                "p_min": thresholds["p_min"],
                "theta_ev": thresholds["theta_ev"],
                "theta_rel": thresholds["theta_rel"],
                "score": thresholds["score"],
            })
            trades, equity, metrics = simulate_book(
                test_scored,
                config=config,
                max_concurrent=max_concurrent,
                p_min=thresholds["p_min"],
                theta_ev=thresholds["theta_ev"],
                theta_rel=thresholds["theta_rel"],
                fold_name=f"{fold_name}_slots_{max_concurrent}",
            )
            metrics.update(
                {
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
                    "train_roc_auc": train_diag["roc_auc"],
                    "test_roc_auc": test_diag["roc_auc"],
                    "train_pr_auc": train_diag["pr_auc"],
                    "test_pr_auc": test_diag["pr_auc"],
                    "train_log_loss": train_diag["log_loss"],
                    "test_log_loss": test_diag["log_loss"],
                    "train_brier": train_diag["brier"],
                    "test_brier": test_diag["brier"],
                    **bench_diag,
                }
            )
            all_fold_metrics.append(metrics)
            if len(trades):
                trades = trades.copy()
                trades["max_concurrent"] = max_concurrent
                trades["fold"] = fold_name
                all_trades.append(trades)
            if len(equity):
                equity = equity.copy()
                equity["max_concurrent"] = max_concurrent
                equity["fold"] = fold_name
                all_equity.append(equity)
        completed_fold_names = completed_fold_names + [fold_name]
        resume_path.write_text(
            json.dumps({
                "input_panel_csv": config.input_panel_csv,
                "include_physics_block": config.include_physics_block,
                "last_completed_fold": fold_num,
                "completed_fold_names": completed_fold_names,
            }, indent=2),
            encoding="utf-8",
        )
        pd.DataFrame(all_fold_metrics).to_csv(output_dir / "fold_metrics.csv", index=False)
        if all_trades:
            pd.concat(all_trades, ignore_index=True).to_csv(output_dir / "trade_blotter.csv", index=False)
        if all_equity:
            pd.concat(all_equity, ignore_index=True).to_csv(output_dir / "equity_curves.csv", index=False)
        if all_feature_importance:
            pd.concat(all_feature_importance, ignore_index=True).to_csv(output_dir / "feature_importances_by_fold.csv", index=False)
        logging.info("Resume: saved state after %s (%s folds completed)", fold_name, len(completed_fold_names))
    fold_metrics_df = pd.DataFrame(all_fold_metrics)
    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    equity_df = pd.concat(all_equity, ignore_index=True) if all_equity else pd.DataFrame()
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
        best_concurrent = int(by_conc.sort_values(["avg_calmar", "avg_expectancy_r"], ascending=[False, False]).iloc[0]["max_concurrent"])
    else:
        by_conc = pd.DataFrame()
        best_concurrent = config.max_concurrent_options[0]
    trades_best = trades_df[trades_df["max_concurrent"] == best_concurrent].copy() if len(trades_df) else pd.DataFrame()
    equity_best = chain_equity_curves(equity_df, best_concurrent, config.starting_capital)
    overall_metrics = compute_metrics(trades_best, equity_best)
    overall_metrics["best_max_concurrent"] = best_concurrent
    overall_metrics["n_folds"] = int(len(fold_metrics_df[fold_metrics_df["max_concurrent"] == best_concurrent])) if len(fold_metrics_df) else 0
    overall_metrics["churn"] = float(trades_best["replacement_exit"].mean()) if "replacement_exit" in trades_best.columns and len(trades_best) else 0.0
    if len(trades_best):
        per_ticker = trades_best.groupby("ticker")["pnl"].sum().abs()
        top_share_abs = float(per_ticker.max() / per_ticker.sum()) if per_ticker.sum() > 0 else 1.0
    else:
        top_share_abs = 1.0
    fold_expectancies = (
        fold_metrics_df[fold_metrics_df["max_concurrent"] == best_concurrent]["expectancy_r"].tolist()
        if len(fold_metrics_df) else []
    )
    research, research_meta = research_score(overall_metrics, fold_expectancies, top_share_abs)
    overall_metrics["research_score"] = research
    overall_metrics.update(research_meta)
    log_overall_summary(overall_metrics)
    best_conc = overall_metrics.get("best_max_concurrent", best_concurrent)
    n_t = overall_metrics.get("n_trades", 0)
    tr = overall_metrics.get("total_return", 0.0)
    cagr = overall_metrics.get("cagr", 0.0)
    mdd = overall_metrics.get("mdd", 0.0)
    calmar = overall_metrics.get("calmar", 0.0)
    pf = overall_metrics.get("profit_factor", 0.0)
    wr = overall_metrics.get("win_rate", 0.0)
    exp_r = overall_metrics.get("expectancy_r", 0.0)
    rs = overall_metrics.get("research_score", 0.0)
    top_conc = overall_metrics.get("top_ticker_share_abs", 0.0)
    churn = overall_metrics.get("churn", 0.0)
    avg_hold = overall_metrics.get("avg_hold_hours", 0.0)
    sharpe = overall_metrics.get("sharpe", 0.0)
    logging.info(
        "Overall Metrics Summary (Concurrency=%s) | Trades: %s | Total Return: %.2f%% | CAGR: %.2f%% | Max Drawdown: %.2f%% | Calmar: %.2f | Profit Factor: %.2f | Win Rate: %.1f%% | Expectancy (R): %.3f | Research Score: %.1f | Top Ticker Concentration: %.1f%% | Churn (Replacements): %.1f%% | Avg Hold (hours): %.0f | Sharpe: %.2f",
        best_conc, n_t, tr * 100, cagr * 100, mdd * 100, calmar, pf, wr * 100, exp_r, rs, top_conc * 100, churn * 100, avg_hold, sharpe,
    )
    feature_stability = pd.DataFrame()
    if len(feature_importance_df):
        feature_stability = (
            feature_importance_df.groupby("feature")["importance"]
            .agg(["mean", "median", "std", "count"])
            .reset_index()
            .sort_values("mean", ascending=False)
        )
    fold_metrics_df.to_csv(output_dir / "fold_metrics.csv", index=False)
    trades_df.to_csv(output_dir / "trade_blotter.csv", index=False)
    equity_df.to_csv(output_dir / "equity_curves.csv", index=False)
    pd.DataFrame(all_thresholds).to_csv(output_dir / "selected_thresholds.csv", index=False)
    by_conc.to_csv(output_dir / "concurrency_comparison.csv", index=False)
    feature_importance_df.to_csv(output_dir / "feature_importances_by_fold.csv", index=False)
    feature_stability.to_csv(output_dir / "feature_stability_summary.csv", index=False)
    (output_dir / "verification.json").write_text(json.dumps(sanitize_for_json(verification), indent=2), encoding="utf-8")
    (output_dir / "config.json").write_text(json.dumps(sanitize_for_json(asdict(config)), indent=2), encoding="utf-8")
    (output_dir / "overall_metrics.json").write_text(json.dumps(sanitize_for_json(overall_metrics), indent=2), encoding="utf-8")
    plot_equity_curve(equity_best, output_dir / "equity_curve_best_concurrency.png", "Equity (best concurrency)")
    report_md = write_markdown_report(output_dir, config, verification, features, fold_metrics_df, overall_metrics, feature_stability)
    summary = {
        "verification": verification,
        "best_concurrency": best_concurrent,
        "overall_metrics": overall_metrics,
        "model_ready_rows": int(len(model_df)),
        "features_used": list(features),
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
        "Total Return: %.2f%%\n"
        "CAGR: %.2f%%\n"
        "Max Drawdown: %.2f%%\n"
        "Calmar: %.2f\n"
        "Profit Factor: %s\n"
        "Win Rate: %.1f%%\n"
        "Expectancy (R): %.3f\n"
        "Research Score: %.1f\n"
        "Top Ticker Concentration: %.1f%%\n"
        "Sharpe: %.2f",
        metrics.get("n_trades", 0),
        metrics.get("total_return", 0.0) * 100,
        metrics.get("cagr", 0.0) * 100,
        metrics.get("mdd", 0.0) * 100,
        metrics.get("calmar", 0.0),
        pf_text,
        metrics.get("win_rate", 0.0) * 100,
        metrics.get("expectancy_r", 0.0),
        metrics.get("research_score", 0.0),
        metrics.get("top_ticker_share_abs", 0.0) * 100,
        metrics.get("sharpe", 0.0),
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
    parser.add_argument("--max_folds", type=int, default=None, help="Run only the first N outer folds (for smoke tests)")
    parser.add_argument("--enable_optuna_tuning", action="store_true", help="Enable Optuna hyperparameter tuning (run baseline first, then enable only if baseline_passed)")
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
        max_folds=getattr(args, "max_folds", None),
        use_optuna_tuning=bool(getattr(args, "enable_optuna_tuning", False)),
    )
    run_pipeline(config)


if __name__ == "__main__":
    main()
