# Pipeline Audit Assessment

**Audit date:** 2025-03-10  
**Scope:** Full repository — Pipeline.py (line-by-line), config, data flows, Blueprint specs  
**Methodology:** Chronology-first, lineage-first, evidence-first; counter-check on all findings

---

## 1. Executive Summary

This repository implements a **walk-forward, event-labeled, probability-calibrated swing-trading research pipeline** in `Pipeline.py` (~4,067 lines). The chronology and lineage controls are **implemented and enforced**:

- **Outer-boundary purge** on `event_end_time` with assertion (L3037–3040)
- **Threshold holdout** scored out-of-sample; thresholds selected only on that holdout (L3305)
- **Calibration holdout** chronologically later than meta-fit; calibrator fit on OOS data (L2061–2097)
- **Imputation** fit on training data only (`impute_fit_transform` L1792–1796)
- **Resume** with config fingerprint; fold skip logic for degenerate splits

**Bottom line:** The pipeline is **methodologically sound** for walk-forward event-labeled research. No confirmed critical defects. Remaining items are design tradeoffs, optional enhancements, and minor engineering gaps.

---

## 2. Repository Scope Audited

**Python files:** `Pipeline.py` (sole executable)

**Config / data:**
- `PipelineConfig` dataclass (L65–137)
- `feature_registry_template.json` (Blueprint)
- `requirements.txt` (pandas, sklearn, xgboost, lightgbm, optuna)

**Data flows:**
- Input: `panel_ohlcv_clean.csv` (ticker, timestamp_utc, open, high, low, close, volume, is_incomplete_session)
- Output tree: `00_logs/`, `01_data/`, `02_metrics/`, `03_features/`, `04_strategies/`, `05_reports/`, `06_state/`

**Rules / specs:** `.cursor/rules/pipeline-auditor-behavior.mdc`, `.cursor/rules/pipeline-research-standards.mdc`, `.cursor/rules/output-and-resume-contract.mdc`, Blueprint docs

**Limitations:** No test suite; audit is code-trace based. Panel regularity assumptions must be validated against actual input data.

---

## 3. Pipeline Map (End-to-End)

| Stage | Function | Line | Description |
|-------|----------|------|-------------|
| 1 | `main()` | 4046 | Parse args, build config |
| 2 | `run_pipeline()` | 2957 | Driver |
| 3 | `load_panel()` | 675 | Read CSV, parse dates, sort |
| 4 | `verify_panel()` | 643 | Required cols, monotonicity, OHLC integrity |
| 5 | `verify_panel_timestamp_regularity()` | 359 | Per-ticker vs global timestamp coverage |
| 6 | `build_feature_matrix()` | 1415 | Per-ticker features + XS z-scores |
| 7 | `add_per_ticker_features()` | 1019 | Rolling/EWM features per ticker |
| 8 | `label_long_events()` | 1457 | Entry at next open, stop/target scan, `event_end_time` |
| 9 | `build_outer_folds()` | 1521 | Expanding folds by calendar months |
| 10 | `purge_outer_train_boundary()` | 1569 | Remove rows with `event_end_time >= cutoff` |
| 11 | Threshold split | 3163–3182 | `threshold_fit_df` vs `threshold_holdout_df` |
| 12 | `fit_and_score_prediction_frame()` | 1799 | Meta + calibrator; score threshold holdout |
| 13 | `fit_outer_fold()` | 1953 | Meta + calibrator; score train/test |
| 14 | `choose_thresholds()` | 2547 | Grid search on `threshold_holdout_scored` |
| 15 | `simulate_book()` | 2263 | Portfolio simulation on test |
| 16 | Subset search | 3266–3332 | On threshold_fit vs threshold_holdout |
| 17 | Permutation importance | 3351–3386 | Train fit, test permute |
| 18 | Regime IC | 3388–3420 | high_vol_34, low_vol_34 (vol_cluster_89 optional) |
| 19 | Seed robustness | 3787–3892 | `evaluate_seed_robustness()` when seed_mode != single |

---

## 4. Chronology Map

### 4.1 Signal / label timing

- **Signal time:** `timestamp_utc[i]` (features from current/past bars only)
- **Entry:** next bar open `open[i+1]` → `entry_open_next`
- **Label resolution:** earliest bar j where stop/target hit, else `max_horizon_bars`; `event_end_time = timestamp_utc[j]`
- **Same-bar stop+target:** stop-first (conservative; L1490–1492)

### 4.2 Outer / holdout / test timing

- **Outer train (pre-purge):** `timestamp_utc < train_end`
- **Outer test:** `test_start <= timestamp_utc < test_end`
- **Outer train (post-purge):** `event_end_time < test_start` enforced (L3037)
- **Threshold holdout:** `timestamp_utc >= max_train_ts - threshold_holdout_months`
- **Threshold fit:** `timestamp_utc < threshold_holdout_start`, purged so `event_end_time < threshold_holdout_start`
- **Calibration holdout:** `timestamp_utc >= max_train_ts - calibration_holdout_months` (distinct from threshold holdout)

### 4.3 Calibration lineage (traced)

- **Meta model:** fit on OOF base predictions from `meta_fit_df` (before calibration holdout)
- **Base models:** fit on `meta_fit_df`; predict on `calibration_holdout_df` (OOS)
- **Calibrator:** fit on `(logit(raw_calib_meta), y_calib)` where `raw_calib_meta` = meta predictions on base predictions on `calibration_holdout_df` (L2092–2097)
- **Calibrator is OOS** relative to meta and base models

### 4.4 Feature chronology

- **Per-ticker features:** rolling/EWM; lookback only (no future)
- **XS z-scores:** `groupby("timestamp_utc")` — at each t, mean/std over tickers at t only (L1430–1434)

---

## 5. Lineage Map (Train vs Test)

| Transform | Fit data | Apply data | Code path |
|-----------|----------|------------|-----------|
| Imputation | train | val/test | `impute_fit_transform(X_train, X_pred)` L1792 |
| Base models | meta_fit_df | calibration_holdout, test | L2082–2085, L2067–2068 |
| Meta model | OOF from meta_fit_df | calibration_holdout, test | L2086–2097 |
| Calibrator | calibration_holdout_df | test | L2097 |
| Threshold selection | — | threshold_holdout_scored only | L3305 |
| Subset search | threshold_fit_df | threshold_holdout_df | L3292–3310 |
| Permutation importance | train_df | test_df | L3351–3386 |

---

## 6. Findings

### 6.1 Confirmed defects

**None.** No critical defects found.

### 6.2 Likely methodological risks

**[MR1] Embargo uses global unique timestamps**

- **Category:** Split integrity (inner CV)
- **Severity:** Medium
- **Confidence:** Medium
- **Evidence:** `purged_splits` (L1544) uses `train_df["timestamp_utc"].drop_duplicates()` and embargo in `embargo_bars` positions. Assumes panel is synchronized across tickers.
- **Mitigation:** Add panel diagnostic in `verify_panel` for per-ticker coverage vs global timestamp set.

**[MR2] Same-bar stop/target ambiguity is stop-first**

- **Category:** Label + simulator consistency
- **Severity:** Low
- **Confidence:** High
- **Evidence:** L1490–1492: `if hit_stop and hit_target: outcome = 0`. Internally consistent but undocumented.

### 6.3 Design tradeoffs

**[DT1] Spearman IC: pooled vs timestamp-level**

- **Evidence:** `spearman_ic()` (L563) uses pooled `s.corr(o, method="spearman")`. Blueprint recommends timestamp-level cross-sectional Spearman. `spearman_ic_by_timestamp()` (L419) exists and is used for fold metrics (L3347–3353); pooled `spearman_ic` is also used for binary IC.
- **Status:** Both exist; timestamp-level IC is already in fold_metrics_row (ic_timestamp_mean, ic_ir, etc.).

**[DT2] Subset search uses classification metrics**

- **Evidence:** L3308–3314: `subset_score = 0.35*pr_auc + 0.25*roc_auc - 0.25*log_loss - 0.15*brier`. Blueprint prefers portfolio metrics for final promotion. Comment at L3306–3307 explains proxy.
- **Status:** Reasonable proxy; portfolio metrics drive `research_score()` and strategy library.

### 6.4 Engineering weaknesses

**[EW1] vol_cluster_high_89 / vol_cluster_low_89 never implemented**

- **Evidence:** L3393–3396 check for these columns; `add_per_ticker_features` (L1375–1376) only creates `vol_cluster_high_34`, `vol_cluster_low_34`. VOLATILITY_CLUSTERING_FEATURES (L203–224) does not list _89 variants.
- **Impact:** Dead optional checks; regime_specs always has at least high_vol_34, low_vol_34. No defect.

**[EW2] Log file location**

- **Evidence:** L476 writes only to `paths.logs_dir / "pipeline.log"` (i.e. `{output_dir}/00_logs/pipeline.log`). No dual/root log. Single authoritative location.

### 6.5 Optional enhancements

- Add panel timestamp-regularity diagnostic in `verify_panel`
- Document stop-first behavior in README
- Implement vol_cluster_high_89 / vol_cluster_low_89 if 89-bar regime is desired

---

## 7. Counter-Check (Evidence Traces)

| Concern | Trace | Result |
|---------|-------|--------|
| Outer-boundary leakage | `purge_outer_train_boundary` L1573; assertion L3037 | **Not confirmed** |
| Threshold selection on train | `choose_thresholds(threshold_holdout_scored, ...)` L3305 | **Not confirmed** |
| Calibrator on meta training data | Calibrator fit on `calibration_holdout_df` L2092–2097 | **Not confirmed** |
| Imputation fit on test | `impute_fit_transform` fits on first arg, transforms second | **Not confirmed** |
| Feature future leakage | Rolling/EWM; XS z-scores by timestamp only | **Not confirmed** |
| Subset search on test | Uses threshold_fit_df vs threshold_holdout_df L3292–3293 | **Not confirmed** |
| Permutation on train labels | perm_model fit on train, permute test features L3351–3386 | **Not confirmed** |

---

## 8. Train-Only Transform Compliance

| Transform | Compliance |
|-----------|------------|
| SimpleImputer | fit on X_train, transform on X_pred (L1795) |
| Base models (RF, ET, XGB, LGBM, ENET) | fit on meta_fit_df / threshold_fit_df |
| Meta model | fit on OOF from meta_fit_df |
| Calibrator | fit on calibration_holdout_df (OOS vs meta) |
| Subset search LogisticRegression | fit on threshold_fit_df, score on threshold_holdout_df |
| Permutation model | fit on train_df, evaluate on test_df |

---

## 9. Seed Sensitivity and IC Logic

- **Seeds:** `resolve_seed_list()` (L2846); modes: single, research (5), final (10)
- **Model seeds:** RF/ET/XGB/LGBM/ENET use `config.random_seed + offset` (L1604–1666)
- **Seed robustness:** `evaluate_seed_robustness()` runs full fold loop with alternate seed; `seed_robustness_summary.csv` when seed_mode != single
- **IC:** `spearman_ic()` pooled; `spearman_ic_by_timestamp()` cross-sectional per timestamp; both in fold metrics

---

## 10. Threshold and Calibration Lineage

- **Threshold selection:** `choose_thresholds(threshold_holdout_scored, ...)` — grid over p_min, theta_ev, theta_rel; `research_score()` for ranking
- **Calibration:** Calibrator fit on `calibration_holdout_df` (OOS); applied to test via `calibrator.predict_proba(logit(raw_test_meta))`

---

## 11. Placeholder / Mocked Logic Check

- **No placeholders:** All stages implemented; no `TODO`, `pass`, or mocked metrics in critical paths
- **No scaffold-only:** Feature registry, subset search, permutation, regime IC all produce real outputs

---

## 12. Redundancy and Inconsistencies

- **vol_cluster_89 checks:** Optional; gracefully no-op when columns absent
- **Logging:** Dual log paths intentional
- **churn:** Added by `simulate_book` to metrics (L2540); `compute_metrics` does not return it; `fold_metrics_row` gets it via `**metrics` from simulate_book

---

## 13. Remediation Design

| Item | Severity | Action |
|------|----------|--------|
| MR1 Panel diagnostic | Medium | Add per-ticker coverage to `verify_panel` return |
| MR2 Stop-first doc | Low | Document in README |
| DT1 Timestamp-level IC | — | Already implemented; used in fold metrics |
| EW1 vol_cluster_89 | Optional | Implement if 89-bar regime desired |

**No mandatory fixes** for chronology, leakage, or calibration.

---

## 14. Final Verdict

**Methodologically sound.**

The pipeline's chronology controls (event-aware outer purge, threshold holdout, calibration holdout), train-only transforms (imputation, subset search, permutation), and threshold-selection lineage are correctly implemented. Calibration is nested and OOS relative to meta and base models.

Remaining items are design tradeoffs (embargo unit, subset search metric) and optional enhancements. The pipeline is suitable for walk-forward event-labeled research. Validate panel timestamp regularity against actual input data before relying on embargo semantics.
