# Swing Trading Research Pipeline

Repository: [https://github.com/cammcnally/new](https://github.com/cammcnally/new)

This repository contains a walk-forward, purged/embargoed, probability-calibrated swing-trading research pipeline for US equities. The current system is Phase 1 governed: it freezes the threshold-search correction boundary, uses stitched outer-test validation for decision metrics, enforces ranking-map guardrails, and treats occupancy as diagnostic only.

This README is the operational bible for the repository. It explains:

- what the pipeline does
- what it is trying to do
- how the current logic works
- how the control plane governs changes
- how to run, test, and validate it
- which artifacts matter and how to read them

If you are changing behavior that affects statistics, promotion rules, outputs, or recovery, read `AGENTS.md` and the Phase 1 docs first.

## Authority And Scope

The canonical governance sources for this repo are:

- `AGENTS.md`
- `docs/phase1-research-spec.md`
- `docs/phase1-execution-roadmap.md`

The README is descriptive. The Phase 1 docs are normative for research semantics. If code and these docs disagree, the docs win until the change is intentionally made and documented.

This repo is intentionally narrower than a full data-platform rebuild. It currently focuses on:

- a single research pipeline
- a single panel-driven input format
- deterministic, auditable research outputs
- reproducible validation and promotion logic
- local-first control-plane enforcement

It is not a live broker stack, not a scheduler-driven platform, and not a full ingestion lakehouse.

## What The Pipeline Does

At a high level, the pipeline:

1. loads a panel CSV containing OHLCV rows and session flags
2. verifies the panel shape, timestamp regularity, and duplicate conditions
3. builds a feature matrix and feature registry
4. generates long-event labels with stop/target and cost-aware logic
5. runs expanding walk-forward outer folds with purged inner CV
6. fits base models, meta-models, and calibration layers
7. applies empirical probability mapping with ranking-map guardrails
8. selects thresholds on an out-of-sample threshold holdout
9. simulates a portfolio with capacity, liquidity, and replacement logic
10. computes stitched policy daily returns and Phase 1 robustness metrics
11. compares model assemblies and emits promotion-support scorecards
12. writes durable artifacts, config snapshots, and resume state

The design goal is not just to produce a backtest. It is to produce a backtest that can be explained, reproduced, audited, and resumed without hidden state.

## Current Phase 1 Contract

Phase 1 freezes the following core meanings:

- `threshold_search_corrected = true`
- `full_pipeline_corrected = false`
- `trial_scope_formal = threshold_policy_search_only`
- `trial_count_formal = 108`
- `max_concurrent = 8` is a hard cap, not a target
- occupancy is diagnostic only
- stitched outer-test calendar-day returns are the basis for final robustness reporting
- ranking-map guardrail failures make a run invalid, not just interesting

Phase 1 also freezes the current statistical language:

- adjusted Sharpe uses Newey-West HAC on calendar-day arithmetic returns
- WRC is fold-local and threshold-family scoped
- deflated Sharpe is reported on stitched outer-test daily returns
- promotion is hierarchical and requires feature validation, model comparison, robustness, and portfolio-policy support

If you want to change any of those meanings, the docs must be updated first.

## Current Implementation Snapshot

As of the current repo state:

- the main research engine lives in `Pipeline.py`
- the control plane lives in `control_plane/` and `tools/control_plane.py`
- the validation layer is a custom contract/sanity checker, not Great Expectations
- the repo stores outputs as CSV, JSON, Markdown, PNG, and resume state files
- the repo already has tests for helper logic, regressions, smoke behavior, and control-plane enforcement
- Phase 2 is optional and refers to auditability/refactor improvements, not required research completion

The current system is already doing real work. This README documents that work rather than pretending the repo is a different architecture.

## Pipeline Architecture

### 1. Input And Verification

The pipeline expects a panel CSV with columns:

- `ticker`
- `timestamp_utc`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `is_incomplete_session`

The loader sorts by `ticker` and `timestamp_utc`, parses timestamps as UTC, and coerces incomplete-session flags to booleans.

The panel verifier checks:

- required columns are present
- duplicate `(ticker, timestamp_utc)` rows are absent
- timestamps are monotonic within each ticker
- timestamp regularity is summarized by ticker
- scattered gaps and late-start tickers are diagnosed rather than silently ignored

This is the first line of defense against broken input data.

### 2. Feature Engineering

The feature layer builds a registry-backed matrix of engineered features. The feature families include:

- returns
- RSI
- MACD
- ATR
- Bollinger-style signals
- volume-derived signals
- cross-sectional z-scores
- optional physics/regime features

The feature registry is persisted so the pipeline can distinguish:

- named features
- default-enabled features
- available vs unavailable features
- family coverage

Feature validation is not just correlation checking. It includes:

- cross-sectional Spearman IC
- HAC t-stats
- sign stability
- regime stability
- monotonicity checks
- incremental lift after costs
- explicit `insufficient_data` handling

### 3. Label Generation

The current label path uses a long-event framing with:

- entry at the next open
- ATR-based stop/target logic
- cost-aware returns
- stop-first handling when stop and target are hit on the same bar

The pipeline produces a `forward_label_return_net` field and a binary `long_win` label. Those are the current research labels, and they drive model training, calibration, IC checks, and threshold-selection logic.

### 4. Walk-Forward Splitting

The outer split logic is expanding-window walk-forward with chronology protection.

Current guardrails include:

- outer-boundary purging
- purged inner CV
- threshold holdout separation
- calibration holdout separation
- embargo bars to reduce leakage risk

The pipeline is designed to keep validation chronology-safe. It is not a random K-fold experiment runner.

### 5. Model Training And Calibration

The current model stack is a classic tabular ensemble:

- Random Forest
- Extra Trees
- XGBoost
- LightGBM
- Elastic Net
- calibrated meta-model output, `p_cal`

The pipeline can optionally use Optuna for a bounded tuning pass, but only after the baseline has passed the current baseline-gating rules.

Important model-flow points:

- base models are fit under purged/embargoed splits
- out-of-fold predictions feed the meta-model
- calibration is chronology-safe and uses a separate holdout inside the purged fit window
- the tuning path is intentionally constrained to prevent runaway search

### 6. Empirical Probability Mapping And Ranking Guardrails

The pipeline transforms calibrated probabilities into an empirical mapping that is monitored for stability.

Guardrails include:

- minimum support rows
- bucket minimums
- maximum fallback usage fraction
- minimum adjacent-fold Spearman
- deterministic simple-rank fallback when support is too thin

This logic is important because the pipeline does not trust a mapping just because it was fit. It checks whether the mapping behaves consistently across folds and whether the fallback rate is acceptable.

### 7. Threshold Search

Threshold selection is performed on a threshold holdout using a fixed family of 108 tuples:

- 9 values of `p_min`
- 4 values of `theta_ev`
- 3 values of `theta_rel`

This is the current threshold-family correction boundary.

For each fold and each concurrency setting, the pipeline:

- simulates the threshold family
- computes candidate diagnostics
- runs fold-local White's Reality Check
- records sufficiency and skip reasons
- selects the best bundle within the corrected family

This is one of the places where the repo is very deliberately narrower than a generic machine-learning system.

### 8. Portfolio Simulation

The simulator is a research book simulator, not a broker.

Current execution logic includes:

- entry at next open
- stop and target checked bar-by-bar
- max concurrent positions capped at 8
- max 2 positions per ticker
- EV-in-R ranking
- replacement exits
- time exits aligned to label geometry
- lagged-liquidity capacity clipping/skipping
- explicit cost and slippage modeling

The repo does not reward full capacity usage. Occupancy is measured, but it is not a target and it is not a promotion criterion.

### 9. Daily Return And Robustness Reporting

The pipeline converts simulation output into policy daily returns and then into stitched outer-test series.

The robustness stack includes:

- calendar-day arithmetic returns
- idle-capital days as zero-return days
- adjusted daily Sharpe
- WRC metadata
- stitched outer-test DSR
- stitched drawdown
- stitched Calmar
- turnover metrics
- holding-period metrics
- capacity diagnostics
- regime-policy diagnostics

The stitched series is the basis for final robustness reporting. Skipped folds stay in the calendar as zero-return windows.

### 10. Model Comparison And Promotion

The current comparison layer evaluates:

- `baseline_linear`
- `baseline_equal_weight_rank_blend`
- `incumbent_ml`

Promotion is not based on a single headline metric. It requires a stronger combined case:

- feature validation must pass
- model comparison must pass
- robustness must pass
- portfolio policy must pass

The current promotion logic also rejects non-positive deflated Sharpe and preserves the distinction between diagnostic occupancy and actual portfolio validity.

### 11. Seed Robustness

The pipeline includes a seed-robustness sweep for the shortlisted strategy. This exists to answer a simple question: does the selected policy survive small RNG changes, or is it a brittle artifact?

## Key Configuration Defaults

These are the most important defaults in `PipelineConfig`:

| Setting | Default | Meaning |
|---|---:|---|
| `max_concurrent_options` | `8` | Hard cap on concurrent positions |
| `max_positions_per_ticker` | `2` | Per-ticker concentration limit |
| `outer_train_months` | `36` | Initial outer training span |
| `outer_test_months` | `6` | Outer test span |
| `inner_folds` | `5` | Purged inner CV folds |
| `embargo_bars` | `105` | Chronology protection buffer |
| `threshold_holdout_months` | `3` | Unbiased threshold selection window |
| `calibration_holdout_months` | `2` | Out-of-sample calibration window |
| `p_min_grid` | `9 values` | Threshold family parameter grid |
| `theta_ev_grid` | `4 values` | Threshold family parameter grid |
| `theta_rel_grid` | `3 values` | Threshold family parameter grid |
| `threshold_wrc_bootstrap_reps` | `250` | WRC bootstrap reps |
| `threshold_wrc_block_length` | `5` | Moving-block bootstrap length |
| `threshold_wrc_alpha` | `0.10` | Fold selection alpha |
| `empirical_prob_map_buckets` | `10` | Ranking-map bucket count |
| `empirical_prob_map_max_fallback_usage_fraction` | `0.25` | Maximum acceptable fallback rate |
| `empirical_prob_map_min_adjacent_fold_spearman` | `0.70` | Stability floor |
| `final_min_oos_daily_observations` | `126` | Minimum stitched OOS observations |
| `bars_per_year` | `252 * 6.5` | Hourly-equivalent annualization |

These values are part of the system semantics, not just tuning knobs.

## Outputs And What They Mean

The pipeline writes all artifacts under `--output_dir`. The authoritative log is `00_logs/pipeline.log`. The only resume checkpoint surface is `06_state/resume_state.json`.

| Directory | File | Purpose |
|---|---|---|
| `00_logs/` | `pipeline.log` | Primary run log |
| `00_logs/` | `panel_timestamp_regularity_summary.json` | Panel coverage summary |
| `00_logs/` | `panel_timestamp_regularity_by_ticker.csv` | Per-ticker coverage diagnostics |
| `01_data/` | `model_ready_dataset.csv` | Labeled, filtered model input |
| `02_metrics/` | `fold_metrics.csv` | Per-fold performance and guardrail evidence |
| `02_metrics/` | `trade_blotter.csv` | Trade-level simulation history |
| `02_metrics/` | `equity_curves.csv` | Fold-level equity curves |
| `02_metrics/` | `selected_thresholds.csv` | Selected threshold tuple per fold |
| `02_metrics/` | `concurrency_comparison.csv` | Aggregates by max concurrency |
| `02_metrics/` | `threshold_candidate_diagnostics.csv` | Candidate-level threshold diagnostics |
| `02_metrics/` | `policy_daily_returns.csv` | Stitched calendar-day return series |
| `02_metrics/` | `overall_metrics.json` | Run-level OOS summary and viability flags |
| `03_features/` | `feature_registry.csv` | Feature registry |
| `03_features/` | `feature_registry_coverage_summary.csv` | Feature coverage summary |
| `03_features/` | `feature_validation_rows.csv` | Fold-level feature validation rows |
| `03_features/` | `feature_validation_ic_daily_rows.csv` | Daily IC rows |
| `03_features/` | `feature_validation_report.csv` | Fold-aggregated feature validation report |
| `03_features/` | `feature_importances_by_fold.csv` | Base-model feature importance by fold |
| `03_features/` | `feature_stability_summary.csv` | Cross-fold importance summary |
| `04_strategies/` | `strategy_library.csv` | Strategy summary table |
| `04_strategies/` | `strategy_scorecards.csv` | Scorecard and promotion support view |
| `04_strategies/` | `model_comparison_report_rows.csv` | Raw model-comparison rows |
| `04_strategies/` | `model_comparison_report.csv` | Aggregated model comparison |
| `04_strategies/` | `position_ranking_audit.csv` | Deterministic ranking / clip / skip audit trail |
| `04_strategies/` | `best_strategy_summary.json` | Best strategy summary |
| `04_strategies/` | `seed_robustness_summary.csv` | Seed-sensitivity summary |
| `05_reports/` | `equity_curve_best_concurrency.png` | Best-concurrency equity chart |
| `05_reports/` | `final_report.md` | Human-readable final report |
| `06_state/` | `resume_state.json` | Resume checkpoint |
| `06_state/` | `config_snapshot.json` | Config and semantic fingerprint |
| `06_state/` | `verification.json` | Input and run verification state |

## Current Status Versus Finished Phase 1

The roadmap currently says the repo has implemented the major Phase 1 mechanics, but some decision-grade work is still pending.

Already in place:

- fixed max concurrent cap of 8
- threshold-family correction for the 108 threshold tuples
- stitched calendar-day outer-test validation
- WRC, DSR, occupancy, turnover, holding-period, capacity, and regime-policy fields
- resume/version fields in canonical artifacts
- feature validation, model comparison, scorecards, and ranking-map guardrails in runtime and artifacts

Still pending at the time of the roadmap snapshot:

- full decision-grade end-to-end validation run
- Tier 1, Tier 2, and Tier 3 smoke validation completion
- canonical reproducibility rerun
- final review of ranking-map guardrail evidence and WRC power on real-run artifacts

That distinction matters. This repo is not pretending to be done just because it can run.

## How To Run It

### Core Research Run

```powershell
.\.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir pipeline_outputs
```

This is the baseline decision-grade run path for the current repo.

### Optional Optuna Run

```powershell
.\.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir pipeline_outputs_optuna `
  --enable_optuna_tuning
```

Optuna tuning is intentionally gated. The baseline should already be strong before you tune.

### Deterministic Reproducibility Run

```powershell
.\.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir pipeline_outputs_repro `
  --deterministic_mode
```

This is the canonical reproducibility path once the main run is stable.

### Smoke Ladder

Use a separate overwrite-oriented directory so smoke artifacts do not mix with the canonical run.

```powershell
.\.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir pipeline_outputs_smoke
```

### Resume

```powershell
.\.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir pipeline_outputs `
  --resume
```

Resume requires the same input and the same output directory. The resume fingerprint will reject mismatched semantics.

## Control Plane And Governance

The control plane is not decorative. It is part of the repo's safety model.

Important surfaces:

- `AGENTS.md` is the canonical policy file
- `tools/control_plane.py` is the local CLI entrypoint
- `control_plane/policy_loader.py` enforces canonical policy bootstrap
- `control_plane/orchestrator.py` routes tasks and roles
- `control_plane/task_state.py` manages task-scaffold state files
- `control_plane/phase1_contract.json` defines artifact contracts
- `contracts/*.lock.json` now hold the tracked bootstrap and projection authority that the control plane trusts by default
- `.agents/skills/*` are the canonical repo-local skills; `.cursor/*` remains generated compatibility output

Common control-plane actions:

```powershell
.\.venv\Scripts\python.exe tools/control_plane.py trust-policy
.\.venv\Scripts\python.exe tools/control_plane.py validate-bootstrap
.\.venv\Scripts\python.exe tools/control_plane.py phase1-change-check --classification docs_only --justification "Docs update"
.\.venv\Scripts\python.exe tools/control_plane.py read-pipeline-log --output-dir pipeline_outputs
```

The repo also uses task workspaces under `.local/control_plane/tasks` with durable state files. That scaffold is not optional when the control plane is in use.

### Control-Plane Roles

The current policy defines these roles:

- `Coordinator` - decomposes tasks, routes work, and owns terminal-state decisions
- `Builder` - makes approved repo changes
- `Runner` - executes approved repo actions
- `Verifier` - validates after edits and writes verifier evidence
- `Auditor` - performs read-only policy and chronology review
- `Watcher` - handles operational recovery
- `DependencyAgent` - proposes or installs dependencies under policy

This matters because the repo is designed to keep policy, execution, and verification separate.

## Dependencies And Environment

### Runtime

- Python `3.11.9`
- Windows workspace
- workspace virtual environment at `.venv`
- Git must be available on `PATH`; this machine now exposes the portable install under `E:\stock_csvs_AI-Perspective\Git\...` through the user `PATH`
- checked-in Codex hooks/config may exist, but native Windows acceptance must not rely on hook execution

### Research Pipeline Dependencies

The core research stack is defined in `requirements.txt`:

- pandas
- pandas-stubs
- numpy
- matplotlib
- scikit-learn
- xgboost
- lightgbm
- tabulate
- optuna

### Control-Plane And Test Dependencies

The control plane and local validation tooling use:

- `requirements-control-plane.txt`
- `requirements-dev.txt`

Typical setup:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-control-plane.txt -r requirements-dev.txt
```

### Path And Output Policy

- the repo resolves paths relative to `PIPELINE_BASE_PATH` if it is set
- otherwise, paths resolve relative to the repo root
- the current pipeline writes into numbered output directories under the configured output path
- the authoritative log is always `00_logs/pipeline.log`
- do not redirect stdout into the log file

## Testing And Validation

The repo includes tests for:

- helper functions
- regression protections
- smoke behavior
- control-plane policy and runtime behavior
- sanity checks on artifact contracts

Common commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -m helper
.\.venv\Scripts\python.exe -m pytest -m regression
.\.venv\Scripts\python.exe -m pytest -m smoke
.\.venv\Scripts\python.exe tools/phase1_sanity_check.py --output_dir pipeline_outputs
```

The artifact sanity checker validates:

- required files exist
- JSON artifacts contain required keys
- CSV artifacts contain required columns
- markdown reports contain required sections
- legacy root-level log/resume surfaces are not reintroduced
- assessment registry records stay well-formed

## What To Preserve When Editing

If you are changing the pipeline, keep these rules in mind:

- do not reward occupancy
- do not broaden the correction boundary without updating the Phase 1 docs first
- do not silently change output schemas
- do not replace the canonical control plane with an alternate one
- do not change resume semantics without updating the fingerprinting and validation logic
- do not conflate diagnostic metrics with promotion criteria

If a change is behaviorally meaningful, it should usually touch code, tests, docs, and state files together.

## What The Repo Should Become Next

The near-term goals, based on the current roadmap, are:

- complete the full decision-grade Phase 1 run
- complete the smoke ladder
- complete the canonical reproducibility rerun
- inspect ranking-map guardrail evidence and WRC power on real artifacts
- only after Phase 1 is stable, consider the optional Phase 2 auditability refactor

Phase 2 is about making the system easier to diagnose and extend. It is not required to declare Phase 1 complete.

## Quick Mental Model

If you need one compact summary of the repo, use this:

- input is a cleaned OHLCV panel with session metadata
- the pipeline builds feature and label layers from that panel
- walk-forward splits protect chronology
- models are trained, calibrated, and compared under a constrained correction boundary
- a threshold family is selected with WRC and ranking-map guardrails
- a simulator turns the policy into daily returns and robustness metrics
- promotion is allowed only when the evidence stack is complete
- the control plane exists to prevent silent drift

## License

Use and modify as needed for research.
