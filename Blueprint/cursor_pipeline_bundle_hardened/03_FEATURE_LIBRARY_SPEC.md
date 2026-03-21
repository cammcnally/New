# Feature Library Specification

> **This master file supersedes both prior versions and incorporates the former addendum. On conflict, the Explicit implementation addendum (Section 6) governs for formulas and implementation details.**

## Scope and design standard

This is the canonical candidate feature library for the 1-hour bar pipeline targeting a holding period of roughly **2 trading days to 3 trading weeks**.

### Source philosophy
Use the Quantified Strategies indicator catalog as a **candidate source** and coverage map, not as a proof ranking. Start from research-backed, widely used indicator families, then let the walk-forward discovery pipeline determine survivors. Reference: https://www.quantifiedstrategies.com/trading-indicators/

The implementation must include:
- **at least 70 regular features**
- **at least 20 physics / fractal / regime features**
- a dedicated **volatility_clustering** family
- exact registry metadata
- point-in-time-safe formulas only

## 1. Global conventions

### 1.1 Core lookback ladder
Use these default bar windows unless a feature definition explicitly overrides them:

- short: `3, 5, 8`
- core: `13, 21, 34, 55`
- extended context: `89`

### 1.2 Price notation
- `O_t` = open at bar t
- `H_t` = high at bar t
- `L_t` = low at bar t
- `C_t` = close at bar t
- `V_t` = volume at bar t
- `TP_t = (H_t + L_t + C_t) / 3`

### 1.3 Return notation
- simple 1-bar return: `r_t = C_t / C_{t-1} - 1`
- log 1-bar return: `lr_t = ln(C_t / C_{t-1})`

### 1.4 Moving average conventions
- EMA_n uses standard exponential weighting with `alpha = 2 / (n + 1)`
- SMA_n is the trailing simple mean over n bars

### 1.5 Volatility conventions
- realized volatility over n bars: standard deviation of trailing 1-bar log returns over n bars
- ATR_n uses Wilder-style smoothing of True Range

### 1.6 Registry rule
Every implemented feature must exist in the registry with:
- exact `feature_name`
- exact `english_name`
- `family`
- `subfamily`
- `regular_or_physics`
- `lookback`
- `parameters`
- `formula_group`
- `depends_on`
- `candidate_group_id`
- `orthogonality_cluster_id`

## 2. Regular feature families

## 2.1 Returns and momentum family

### Formula group: `simple_return_n`
`ret_n = C_t / C_{t-n} - 1`

Implement:
- `ret_1`
- `ret_2`
- `ret_3`
- `ret_5`
- `ret_8`
- `ret_13`
- `ret_21`
- `ret_34`
- `ret_55`

### Formula group: `log_return_1`
`logret_1 = ln(C_t / C_{t-1})`

Implement:
- `logret_1`

### Formula group: `rolling_return_z_n`
`ret_z_n = (ret_1 - mean(ret_1, n)) / std(ret_1, n)`

Implement:
- `ret_z_13`
- `ret_z_34`

### Formula group: `cumulative_return_n`
`cumret_n = product(1 + r_i over last n bars) - 1`

Implement:
- `cumret_13`
- `cumret_34`
- `cumret_55`

### Formula group: `up_bar_ratio_n`
`up_bar_ratio_n = mean(1[r_i > 0] over last n bars)`

Implement:
- `up_bar_ratio_13`
- `up_bar_ratio_34`

### Formula group: `momentum_spread`
Implement:
- `momentum_5_over_21 = ret_5 - ret_21`
- `momentum_13_over_34 = ret_13 - ret_34`

## 2.2 Moving-average / trend family

### Formula group: `ema_gap_a_b`
`ema_gap_a_b = EMA_a(C)_t / EMA_b(C)_t - 1`

Implement:
- `ema_gap_5_13`
- `ema_gap_13_34`
- `ema_gap_34_55`
- `ema_gap_55_89`

### Formula group: `sma_gap_a_b`
`sma_gap_a_b = SMA_a(C)_t / SMA_b(C)_t - 1`

Implement:
- `sma_gap_13_34`
- `sma_gap_34_55`

### Formula group: `price_vs_ema_n`
`price_vs_ema_n = C_t / EMA_n(C)_t - 1`

Implement:
- `price_vs_ema_13`
- `price_vs_ema_34`
- `price_vs_ema_55`

### Formula group: `price_vs_sma_n`
`price_vs_sma_n = C_t / SMA_n(C)_t - 1`

Implement:
- `price_vs_sma_21`
- `price_vs_sma_55`

### Formula group: `ema_slope_n_k`
`ema_slope_n = (EMA_n(C)_t - EMA_n(C)_{t-k}) / EMA_n(C)_{t-k}`

Defaults:
- `k = 3` for `n=13`
- `k = 5` for `n=34`
- `k = 8` for `n=55`

Implement:
- `ema_slope_13`
- `ema_slope_34`
- `ema_slope_55`

### Formula group: `trend_persistence_n`
`trend_persistence_n = mean(1[EMA_13 > EMA_34] over last n bars)`

Implement:
- `trend_persistence_13`
- `trend_persistence_34`

## 2.3 Oscillator family

### Formula group: `rsi_n`
Wilder RSI over n bars.

Implement:
- `rsi_7`
- `rsi_14`
- `rsi_21`

### Formula group: `stoch_k_n_s`
`stoch_k_n_s = SMA_s( 100 * (C_t - rolling_min(L,n)) / (rolling_max(H,n) - rolling_min(L,n)) )`

Implement:
- `stoch_k_14_3`
- `stoch_d_14_3`
- `stoch_k_21_3`
- `stoch_d_21_3`

### Formula group: `williams_r_n`
`williams_r_n = -100 * (rolling_max(H,n) - C_t) / (rolling_max(H,n) - rolling_min(L,n))`

Implement:
- `williams_r_14`
- `williams_r_21`

### Formula group: `cci_n`
`CCI_n = (TP_t - SMA_n(TP)_t) / (0.015 * mean_abs_dev(TP over n))`

Implement:
- `cci_20`
- `cci_34`

## 2.4 MACD / PPO family

### Formula group: `macd_fast_slow_signal`
`MACD = EMA_fast(C) - EMA_slow(C)`
`Signal = EMA_signal(MACD)`
`Hist = MACD - Signal`

Implement:
- `macd_12_26_9`
- `macd_signal_12_26_9`
- `macd_hist_12_26_9`
- `macd_13_34_8`
- `macd_signal_13_34_8`
- `macd_hist_13_34_8`

### Formula group: `ppo_fast_slow`
`PPO = 100 * (EMA_fast(C) - EMA_slow(C)) / EMA_slow(C)`

Implement:
- `ppo_12_26`

## 2.5 Volatility and range family

### Formula group: `atr_n`
`TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)`
`ATR_n` = Wilder-smoothed TR over n bars

Implement:
- `atr_14`
- `atr_21`
- `atr_34`

### Formula group: `atr_pct_n`
`atr_pct_n = ATR_n / C_t`

Implement:
- `atr_pct_14`
- `atr_pct_21`
- `atr_pct_34`

### Formula group: `true_range_pct`
`tr_pct_1 = TR_t / C_t`

Implement:
- `tr_pct_1`

### Formula group: `realized_vol_n`
`realized_vol_n = std(lr_t over n bars)`

Implement:
- `realized_vol_13`
- `realized_vol_34`
- `realized_vol_89`

### Formula group: `vol_of_vol_n`
`vol_of_vol_n = std(realized_vol_13 over n bars)`

Implement:
- `vol_of_vol_13`
- `vol_of_vol_34`

### Formula group: `range_pct_n`
`range_pct_n = (rolling_max(H,n) - rolling_min(L,n)) / C_t`

Implement:
- `range_pct_1`
- `range_pct_5`
- `range_pct_13`

### Formula group: `parkinson_vol_n`
`parkinson_vol_n = sqrt( mean( (ln(H/L))^2 over n ) / (4 * ln(2)) )`

Implement:
- `parkinson_vol_13`
- `parkinson_vol_34`

### Formula group: `garman_klass_vol_n`
Use the standard Garman-Klass estimator over n bars.

Implement:
- `garman_klass_vol_13`

## 2.6 Channel / breakout family

### Formula group: `bb_pos_n_k`
`BB_mid = SMA_n(C)`
`BB_up = BB_mid + k * std(C,n)`
`BB_dn = BB_mid - k * std(C,n)`
`bb_pos = (C_t - BB_dn) / (BB_up - BB_dn)`

Implement:
- `bb_pos_20_2`
- `bb_width_20_2`
- `bb_pos_34_2`
- `bb_width_34_2`

### Formula group: `keltner_pos_n_m`
`KC_mid = EMA_n(C)`
`KC_up = KC_mid + m * ATR_n`
`KC_dn = KC_mid - m * ATR_n`
`keltner_pos = (C_t - KC_dn) / (KC_up - KC_dn)`

Defaults:
- `n=20, m=2`

Implement:
- `keltner_pos_20_2`
- `keltner_width_20_2`

### Formula group: `donchian_pos_n`
`donchian_pos_n = (C_t - rolling_min(L,n)) / (rolling_max(H,n) - rolling_min(L,n))`

Implement:
- `donchian_pos_20`
- `donchian_pos_55`

### Formula group: `donchian_breakout_n`
`breakout_up_n = 1[C_t > rolling_max(H,n).shift(1)]`
`breakout_down_n = 1[C_t < rolling_min(L,n).shift(1)]`

Implement:
- `breakout_up_20`
- `breakout_up_55`
- `breakout_down_20`
- `breakout_down_55`

### Formula group: `squeeze_on_20`
`1[BB_width_20_2 < keltner_width_20_2]`

Implement:
- `squeeze_on_20`

## 2.7 Trend-strength family

### Formula group: `adx_n`
Standard Wilder ADX over n bars.

Implement:
- `adx_14`
- `adx_21`

### Formula group: `di_n`
Standard Wilder +DI and -DI over n bars.

Implement:
- `plus_di_14`
- `minus_di_14`
- `plus_di_21`
- `minus_di_21`

### Formula group: `adx_slope`
`adx_slope_5 = (ADX_14_t - ADX_14_{t-5}) / 5`

Implement:
- `adx_slope_5`

## 2.8 Volume / flow family

### Formula group: `vol_z_n`
`vol_z_n = (V_t - mean(V,n)) / std(V,n)`

Implement:
- `vol_z_20`
- `vol_z_60`

### Formula group: `rel_volume_n`
`rel_volume_n = V_t / mean(V,n)`

Implement:
- `rel_volume_20`
- `rel_volume_60`

### Formula group: `volume_ema_gap`
`volume_ema_gap_10_20 = EMA_10(V) / EMA_20(V) - 1`

Implement:
- `volume_ema_gap_10_20`

### Formula group: `obv_slope_n`
`OBV_t = cumulative(sign(C_t - C_{t-1}) * V_t)`
`obv_slope_n = (OBV_t - OBV_{t-n}) / n`

Implement:
- `obv_slope_5`
- `obv_slope_13`

### Formula group: `cmf_n`
Standard Chaikin Money Flow over n bars.

Implement:
- `cmf_20`

### Formula group: `mfi_n`
Standard Money Flow Index over n bars.

Implement:
- `mfi_14`

### Formula group: `force_index_n`
`force_index_n = EMA_n( (C_t - C_{t-1}) * V_t )`

Implement:
- `force_index_13`

### Formula group: `vpt_n`
`VPT_t = cumulative( V_t * (C_t - C_{t-1}) / C_{t-1} )`
`vpt_slope_13 = (VPT_t - VPT_{t-13}) / 13`

Implement:
- `vpt_slope_13`

## 2.9 VWAP / support / resistance / anatomy family

### Formula group: `session_vwap_dist`
Session VWAP resets each trading session:
`session_vwap_t = cumulative(TP_i * V_i within session) / cumulative(V_i within session)`
`session_vwap_dist = C_t / session_vwap_t - 1`

Implement:
- `session_vwap_dist`

### Formula group: `rolling_vwap_dist_n`
`rolling_vwap_n = sum(TP_i * V_i over n) / sum(V_i over n)`
`rolling_vwap_dist_n = C_t / rolling_vwap_n - 1`

Implement:
- `rolling_vwap_dist_13`
- `rolling_vwap_dist_34`

### Formula group: `pivot_dist_prev_day`
Previous-day floor pivot:
`pivot_prev_day = (H_prev_day + L_prev_day + C_prev_day) / 3`
`pivot_dist_prev_day = (C_t - pivot_prev_day) / C_t`

Implement:
- `pivot_dist_prev_day`

### Formula group: `dist_to_roll_high_n`
`dist_to_roll_high_n = (C_t - rolling_max(H,n).shift(1)) / C_t`

Implement:
- `dist_to_roll_high_20`
- `dist_to_roll_high_55`

### Formula group: `dist_to_roll_low_n`
`dist_to_roll_low_n = (C_t - rolling_min(L,n).shift(1)) / C_t`

Implement:
- `dist_to_roll_low_20`
- `dist_to_roll_low_55`

### Formula group: `range_position_n`
`range_position_n = (C_t - rolling_min(L,n)) / (rolling_max(H,n) - rolling_min(L,n))`

Implement:
- `range_position_20`
- `range_position_55`

### Formula group: `body_pct`
`body_pct_1 = |C_t - O_t| / max(H_t - L_t, eps)`

Implement:
- `body_pct_1`

### Formula group: `upper_wick_pct`
`upper_wick_pct_1 = (H_t - max(C_t, O_t)) / max(H_t - L_t, eps)`

Implement:
- `upper_wick_pct_1`

### Formula group: `lower_wick_pct`
`lower_wick_pct_1 = (min(C_t, O_t) - L_t) / max(H_t - L_t, eps)`

Implement:
- `lower_wick_pct_1`

### Formula group: `close_location_value`
`close_location_value_1 = (2*C_t - H_t - L_t) / max(H_t - L_t, eps)`

Implement:
- `close_location_value_1`

### Formula group: `gap_open_pct`
`gap_open_pct_1 = (O_t - C_{t-1}) / C_{t-1}`

Implement:
- `gap_open_pct_1`

## 2.10 Cross-sectional family

These are computed at each timestamp across the active universe using only information available at that timestamp.

### Formula group: `xs_zscore_feature`
`xs_feature_z = (feature_ticker_t - mean(feature_all_tickers_t)) / std(feature_all_tickers_t)`

Implement:
- `xs_ret_13_z`
- `xs_ret_34_z`
- `xs_rsi_14_z`
- `xs_atr_pct_14_z`
- `xs_rel_volume_20_z`

## 2.11 Volatility clustering family

This family is regular/regime-context, not hard policy logic.

### Formula group: `vol_pct_rank_n`
`vol_pct_rank_n = percentile_rank(realized_vol_13 within trailing n bars)`

Implement:
- `vol_pct_rank_34`
- `vol_pct_rank_89`

### Formula group: `vol_cluster_flag`
Implement:
- `vol_cluster_high_34 = 1[vol_pct_rank_34 >= 0.80]`
- `vol_cluster_low_34 = 1[vol_pct_rank_34 <= 0.20]`

### Formula group: `vol_persistence_n`
`vol_persistence_high_n = mean(vol_cluster_high_34 over last n bars)`
`vol_persistence_low_n = mean(vol_cluster_low_34 over last n bars)`

Implement:
- `vol_persistence_high_13`
- `vol_persistence_high_34`
- `vol_persistence_low_13`
- `vol_persistence_low_34`

### Formula group: `consecutive_state_bars`
Run-length since last state change.

Implement:
- `consecutive_high_vol_bars`
- `consecutive_low_vol_bars`

### Formula group: `vol_regime_change_k`
`vol_regime_change_k = vol_pct_rank_34 - vol_pct_rank_34.shift(k)`

Implement:
- `vol_regime_change_5`
- `vol_regime_change_13`

### Formula group: `vol_spike_flag`
`vol_spike_flag = 1[ realized_vol_13 > mean(realized_vol_13,34) + 2*std(realized_vol_13,34) ]`

Implement:
- `vol_spike_flag`

### Formula group: `vol_cooling_flag`
`vol_cooling_flag = 1[ realized_vol_13 < mean(realized_vol_13,34) - 1*std(realized_vol_13,34) ]`

Implement:
- `vol_cooling_flag`

### Formula group: `vol_context_interactions`
Keep only a small curated set:
- `vol_x_momentum_13 = realized_vol_13 * ret_13`
- `vol_x_trend_strength = realized_vol_13 * adx_14`
- `vol_x_breakout_state = realized_vol_13 * breakout_up_20`
- `vol_x_rel_volume = realized_vol_13 * rel_volume_20`

## 3. Physics / fractal / regime features

## 3.1 Hurst / variance-ratio family

### Formula group: `hurst_proxy_n`
Use the variance-ratio-based proxy:
`hurst_proxy_n = 0.5 * (1 + ln(VR_lag,n) / ln(lag))`

Implement:
- `hurst_proxy_34`
- `hurst_proxy_55`
- `hurst_proxy_89`

### Formula group: `variance_ratio_lag_n`
`VR_lag,n = var(C_t - C_{t-lag} over n) / (lag * var(C_t - C_{t-1} over n))`

Implement:
- `variance_ratio_5_34`
- `variance_ratio_5_55`
- `variance_ratio_13_89`

## 3.2 Entropy family

### Formula group: `entropy_sign_n`
Let `p_n = mean(1[r_i > 0] over n)`
`entropy_sign_n = -( p_n*ln(p_n) + (1-p_n)*ln(1-p_n) ) / ln(2)`

Implement:
- `entropy_sign_20`
- `entropy_sign_34`
- `entropy_sign_55`

### Formula group: `entropy_return_hist_n`
Histogram entropy of 1-bar returns over n bars using fixed binning.

Implement:
- `entropy_return_hist_20`
- `entropy_return_hist_34`

## 3.3 Autocorrelation family

### Formula group: `autocorr_k_n`
Standard Pearson autocorrelation of `r_t` with `r_{t-k}` over trailing n bars.

Implement:
- `autocorr_1_20`
- `autocorr_1_34`
- `autocorr_5_34`

### Formula group: `autocorr_absret_k_n`
Autocorrelation of absolute returns over trailing n bars.

Implement:
- `autocorr_absret_1_20`
- `autocorr_absret_1_34`

## 3.4 Fractal / path complexity family

### Formula group: `fractal_dimension_proxy_n`
`fractal_dimension_proxy_n = 1 + ( ln(sum(TR over n)) - ln(rolling_max(H,n) - rolling_min(L,n)) ) / ln(n)`

Implement:
- `fractal_dimension_proxy_20`
- `fractal_dimension_proxy_34`
- `fractal_dimension_proxy_55`

### Formula group: `pfe_n`
Polarized Fractal Efficiency:
`PFE_n = 100 * sign(C_t - C_{t-n}) * sqrt((C_t - C_{t-n})^2 + n^2) / sum_{i=t-n+1..t} sqrt((C_i - C_{i-1})^2 + 1^2)`

Implement:
- `pfe_13`
- `pfe_34`

### Formula group: `roughness_index_n`
`roughness_index_n = sum(TR over n) / max(rolling_max(H,n) - rolling_min(L,n), eps)`

Implement:
- `roughness_index_20`
- `roughness_index_34`

## 3.5 Fractional / distribution-shape family

### Formula group: `fracret_d`
Fractionally weighted return transform using fixed coefficient vectors.

Implement:
- `fracret_0_35`
- `fracret_0_50`

### Formula group: `rolling_skew_n`
Standard skewness of `lr_t` over trailing n bars.

Implement:
- `rolling_skew_34`

### Formula group: `rolling_kurt_n`
Standard kurtosis of `lr_t` over trailing n bars.

Implement:
- `rolling_kurt_34`

## 3.6 Regime-duration family

### Formula group: `regime_duration_high_vol`
Run-length of `vol_cluster_high_34 == 1`

Implement:
- `regime_duration_high_vol`

### Formula group: `regime_duration_low_vol`
Run-length of `vol_cluster_low_34 == 1`

Implement:
- `regime_duration_low_vol`

## 4. Family-specific pruning expectations

- `moving_average_trend`: prune aggressively; many near-duplicates
- `oscillators`: allow at most a small number of survivors unless clearly incremental
- `volatility_range`: avoid carrying multiple substitute estimators without lift proof
- `channel_breakout`: prefer one representative per near-duplicate cluster
- `volume_flow`: keep complementary flow/activity measures, not many substitutes
- `volatility_clustering`: keep as context family; do not let it exceed family cap
- `physics_fractal_regime`: allow only stable, non-fragile members

## 5. Required minimum implemented counts

The implementation must contain at least:
- **70 regular features** from Sections 2.1 through 2.11
- **20 physics / fractal / regime features** from Section 3

The easiest compliant implementation is to implement all named features in this file.

---

## 6. Explicit implementation addendum (authoritative for formulas)

The following conventions and formulas override any shorthand above. For 1-hour bars, target holding period ~2 trading days to 3 trading weeks.

### 6.1 Global implementation conventions

**Time indexing**: All features at time `t` must be computed using information available **at or before bar close t**. No feature may use `O_{t+1}`, `H_{t+1}`, `L_{t+1}`, `C_{t+1}`, `V_{t+1}` unless explicitly part of a **label** rather than a feature.

**Warmup / minimum periods**: For any feature with lookback `n`: output `NaN` until enough history exists; do **not** backfill or forward-fill engineered features by default; imputation, if used, must happen inside the model pipeline and be fit on training data only.

**Numerical safety**: Use `eps = 1e-12` for denominator protection; if denominator absolute value `< eps`, return `NaN` unless the feature explicitly calls for a bounded fallback.

**Rolling-window inclusion**: Unless otherwise stated, rolling functions include the **current bar t**. Example: `rolling_max(H, 20)` at time `t` uses bars `[t-19, ..., t]`.

**Shift convention for breakout / support / resistance**: If a feature measures distance to a level known **before** the current bar closed, shift the level by 1 bar. Example: `dist_to_roll_high_20 = (C_t - rolling_max(H,20)_{t-1}) / C_t`.

**Session convention**: A "session" means the exchange trading day. Use the panel's exchange-local session calendar. If the input panel includes `session_date`, use that as the grouping key; otherwise derive session date from exchange-local timestamp.

### 6.2 Exact indicator formulas (replace shorthand where applicable)

**RSI (Wilder)**: `delta_t = C_t - C_{t-1}`; `gain_t = max(delta_t, 0)`; `loss_t = max(-delta_t, 0)`. Initial: `avg_gain_n = mean(gain over first n bars)`; `avg_loss_n = mean(loss over first n bars)`. Wilder smoothing: `avg_gain_t = ((n-1)*avg_gain_{t-1} + gain_t)/n`; `avg_loss_t = ((n-1)*avg_loss_{t-1} + loss_t)/n`. `RS_t = avg_gain_t / max(avg_loss_t, eps)`; `RSI_t = 100 - 100/(1+RS_t)`.

**ADX / +DI / -DI (Wilder)**: Standard TR, +DM/-DM, Wilder smoothing, `+DI_t = 100*(+DM_smoothed/max(ATR,eps))`, `-DI_t` analogous, `DX_t = 100*|+DI - -DI|/max(+DI+-DI,eps)`, ADX = Wilder-smoothed DX.

**CMF**: `MFM_t = ((C-L)-(H-C))/max(H-L,eps)`; `MFV_t = MFM_t*V_t`; `CMF_n = sum(MFV over n)/max(sum(V over n),eps)`.

**MFI**: Typical price `TP`, raw money flow `RMF = TP*V`; positive/negative flow over n; `MR = PMF_n/max(NMF_n,eps)`; `MFI = 100 - 100/(1+MR)`.

**Garman-Klass volatility**: `u_t = ln(H_t/max(O_t,eps))`, `d_t = ln(L_t/max(O_t,eps))`, `c_t = ln(C_t/max(O_t,eps))`. Per-bar: `GKVar_t = 0.5*(u-d)^2 - (2*ln(2)-1)*c^2`. Rolling: `garman_klass_vol_n = sqrt(mean(max(GKVar,0) over n))`.

**Session VWAP**: `session_vwap_t = cum_pv_t/max(cum_v_t,eps)` within session; `session_vwap_dist = C_t/max(session_vwap_t,eps) - 1`. Session resets each trading day.

**Pivot (previous day)**: `pivot_prev_day = (H_prev+L_prev+C_prev)/3`; `pivot_dist_prev_day = (C_t - pivot_prev_day)/max(C_t,eps)`.

**Percentile-rank volatility**: `vol_pct_rank_n = rank(x_t within W_t)/len(W_t)` in [0,1]; `vol_cluster_high_34 = 1[vol_pct_rank>=0.80]`; `vol_cluster_low_34 = 1[vol_pct_rank<=0.20]`.

**Histogram entropy of returns**: For lookback n, collect trailing 1-bar log returns R_t = {lr_{t-n+1},...,lr_t}. Use fixed `num_bins = 10`. Use rolling min/max from R_t to define bin edges. Convert counts to probabilities p_i = count_i/n. `entropy_return_hist_n = - sum_i p_i * ln(p_i)` over bins with p_i > 0. Optionally normalize by ln(num_bins) for bounded [0,1] output; choose one convention and keep consistent. Implement: `entropy_return_hist_20`, `entropy_return_hist_34`.

**Entropy of sign**: `p_n = mean(1[r_i>0] over n)`; if p∈{0,1} then 0; else `entropy_sign_n = -(p*ln(p)+(1-p)*ln(1-p))/ln(2)`.

**Fractal dimension proxy**: `path_n = sum(TR over n)`; `range_n = rolling_max(H,n)-rolling_min(L,n)`; `fractal_dimension_proxy_n = 1 + (ln(max(path,eps))-ln(max(range,eps)))/ln(n)`.

**PFE**: `disp_n = C_t - C_{t-n}`; `straight_n = sign(disp)*sqrt(disp^2+n^2)`; `path_n = sum sqrt((C_i-C_{i-1})^2+1)`; `PFE_n = 100*straight_n/max(path_n,eps)`.

**Cross-sectional z-scores**: `xs_f_z = (f_ticker - mu_t)/max(sigma_t,eps)`; if sigma<eps return 0.0.

**Run-length / regime duration**: First bar of newly entered regime counts as 1. Apply to `consecutive_high_vol_bars`, `consecutive_low_vol_bars`, `regime_duration_high_vol`, `regime_duration_low_vol`.

**Fractional-return transforms**: Recursive weights `w_k = -w_{k-1}*(d-k+1)/k`; `fracret_d = sum w_k * r_{t-k}`. Defaults: `fracret_0_35` (d=0.35,m=50), `fracret_0_50` (d=0.50,m=50). Output NaN until m observations exist.

### 6.3 Additional implementation conventions

**Missing bars / irregular sessions**: Compute rolling features on the actual observed sequence; do not infer synthetic bars; session-based features group by actual session date.

**Indicator family pruning defaults**: correlation threshold 0.80; no family >30% of final selected features; moving-average and oscillator families pruned more aggressively.

**Stability thresholds**: promote if fold stability >=70%; reject if <50% unless ablation shows exceptional incremental lift.

**Volatility-clustering family role**: Context variables, not hard-coded trade blockers. Do not convert to hard entry filters unless ablation and OOS evidence strongly support it.
