# Pipeline Validity Assessment

**Date:** 2026-03-29
**Assessor:** Automated analysis of code, logs, and artifacts

## Executive Summary

The core research pipeline (Pipeline.py) is functional and actively producing results. The most recent run completed 3 of 19 outer folds with no errors before being interrupted during fold 4. The environment, dependencies, and configuration are correctly set up. The new infrastructure modules (Dagster, GE, DVC, MLflow, feature registry, lineage) are scaffolded but not yet integrated into the core execution path.

## 1. Does It Run?

**Yes.** Evidence:

- **Most recent run:** Started 2026-03-29 13:42:13 as a fresh run (not resume)
- **Data loaded:** 351,703 rows across 17 tickers (AMAT, AMD, B, CAT, CCJ, CRWD, CSCO, ES, ITW, LLY, LMT, LRCX, MSFT, MU, PFE, RTX, T)
- **Date range:** 2014-01-02 to 2026-02-12
- **Feature matrix:** Built successfully for all 17 tickers
- **Model-ready dataset:** Written to `01_data/model_ready_dataset.csv`
- **Walk-forward folds:** 19 folds identified, folds 1-3 completed fully
- **Last log entry:** Fold 4 threshold evaluation in progress (15:44:05)
- **Error count:** Zero ERROR or Traceback lines in pipeline.log

### Environment

| Check | Status |
|-------|--------|
| Python version | 3.11.9 (matches `.python-version` and Pipeline.py guard) |
| Virtual environment | `.venv/` exists, pyvenv.cfg confirms 3.11.9 |
| xgboost (required) | Available per import |
| lightgbm (optional) | Available per log |
| optuna (optional) | Available per log |
| pandas, numpy, sklearn, matplotlib | Declared in pyproject.toml |

### What Would Break

| Failure mode | Cause |
|-------------|-------|
| `SystemExit` at import | Python outside [3.11.9, 3.12.0) |
| `ImportError` | Missing xgboost, sklearn, pandas, numpy, or matplotlib |
| `FileNotFoundError` | Missing `--input_panel_csv` |
| `RuntimeError` | Invalid cost model configuration |
| Resume fingerprint mismatch | `--resume` with different config vs original run |

## 2. Does It Run As Intended?

**Yes, within the completed scope.** The pipeline implements its stated Phase 1 semantics:

### Implemented and Working (verified via artifacts and logs)

- **Walk-forward splits:** Expanding-window outer folds with chronology protection, purged inner CV, embargo bars, separate threshold holdout and calibration holdout windows
- **108-tuple threshold family:** Grid search over 9 p_min x 4 theta_ev x 3 theta_rel values with fold-local WRC evaluation
- **Model stack:** Random Forest, Extra Trees, XGBoost, LightGBM base learners with calibrated meta-model
- **Portfolio simulation:** Capacity-constrained with max 8 concurrent positions, 2 per ticker, EV-in-R ranking, lagged-liquidity clipping
- **Feature engineering:** Registry-backed per-ticker features (returns, RSI, MACD, ATR, Bollinger, volume, cross-sectional z-scores)
- **Feature validation:** Spearman IC, HAC t-stats, sign stability, regime stability, monotonicity checks
- **Cost model:** Slippage, overnight brokerage, capacity drag explicitly modeled
- **Resume:** Deterministic checkpoint with config fingerprinting (resume_state.json correctly records last_completed_fold: 3)
- **Artifact layout:** Structured numbered output directories with CSV, JSON, and Markdown artifacts
- **Ranking-map guardrails:** Minimum support, bucket minimums, fallback usage limits, adjacent-fold Spearman stability

### Not Yet Completed

- **Full 19-fold run:** Only folds 1-3 complete; fold 4 was interrupted during threshold evaluation for the baseline_equal_weight_rank_blend model comparison
- **Final report:** `05_reports/final_report.md` is not yet generated (requires all folds complete)
- **Promotion decision:** Overall promotion_pass/robustness_pass flags not yet computed
- **Seed robustness sweep:** Runs after fold completion, not yet reached
- **Stitched OOS metrics:** Requires all folds to produce the stitched outer-test daily return series

## 3. Does It Achieve Its Aims?

**Partially -- the mechanism is sound but the full run has not completed.**

The pipeline's aim is to produce a backtest that can be explained, reproduced, audited, and resumed without hidden state. Based on the evidence:

| Aim | Status | Evidence |
|-----|--------|----------|
| Explainable | Yes | Feature registry, fold metrics, trade blotter, threshold diagnostics all written as structured CSVs |
| Reproducible | Partially | Config snapshot with hashes exists; deterministic_mode available; full reproducibility rerun not yet done |
| Auditable | Yes | Position ranking audit trail, per-fold IC and importance data, WRC metadata all persisted |
| Resumable | Yes | resume_state.json correctly records fold 3 completion; --resume flag supported |
| No hidden state | Yes | All config, seeds, and fingerprints written to config_snapshot.json |

## 4. Infrastructure Module Status

| Module | Status | Notes |
|--------|--------|-------|
| Pipeline.py (core) | Working | Runs, produces artifacts, resumes correctly |
| control_plane/ | Working | Policy loader, orchestrator, verifiers all functional |
| dagster_pipeline/ | Scaffolded | Wraps Pipeline.py functions as assets; not yet the primary execution path |
| gx/ (Great Expectations) | Scaffolded | 4 expectation suites defined; not yet wired into pipeline execution |
| feature_registry/ | Scaffolded | 9 features defined in YAML; tests pass; not yet consumed by Pipeline.py |
| mlflow_integration/ | Scaffolded | Tracking and registry code written; not yet called from Pipeline.py |
| lineage/ | Scaffolded | OpenLineage emitter and file transport; not yet called from Pipeline.py |
| DVC | Scaffolded | dvc.yaml with train + evaluate stages; not yet used for data versioning |
| GitHub Actions CI | Defined | 8 workflow files; repo not yet pushed with branch protections |

## 5. Recommendations

1. **Complete the full run:** Resume the current smoke run (`--resume`) to finish all 19 folds and produce the final report
2. **Run the test suite:** Execute `uv run python -m pytest -q` to verify all tests pass after the recent restructuring
3. **Integrate infrastructure:** Wire MLflow tracking and GE validation into Pipeline.py's run_pipeline() function
4. **Push to GitHub:** Enable CI workflows, configure protected environments for model-promotion and release
5. **Run DVC:** Execute `dvc repro` to establish the first versioned pipeline run

## 6. Key Metrics from Most Recent Run (Folds 1-3)

From `fold_metrics.csv` and `resume_state.json`:

- **Threshold search:** corrected=true, 108-tuple family
- **Walk-forward:** 36-month initial train, 6-month test windows
- **Inner CV:** 5 purged folds with 105-bar embargo
- **Cost model:** slippage=0.0001, overnight_brokerage=0.0003
- **Max concurrent:** 8 positions
- **Panel coverage:** 99.9% median ticker coverage (1 ticker at 55% due to later IPO)
