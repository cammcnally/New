# Output File Policy

> **This master file supersedes both prior versions. On conflict, Section A governs.**

## 1. Goals

The pipeline must:
- avoid file explosion
- keep outputs easy to assess
- overwrite current-state artifacts by default
- preserve only the state files needed for durability and resume
- invalidate stale reports on fresh runs
- keep names short, explicit, and sortable

## 2. Drive and location

All outputs must be saved to the E: drive under `E:\stock_csvs_AI-Perspective`. The pipeline uses a canonical base (`E:\stock_csvs_AI-Perspective\NEW` by default; override via env `PIPELINE_BASE_PATH`). Run from project root.

## 3. Required output tree

Use:

- `00_logs/`
- `01_data/`
- `02_metrics/`
- `03_features/`
- `04_strategies/`
- `05_reports/`
- `06_state/`

## 4. File classes

### 4.1 Current-state artifacts
These describe the current run state and should overwrite by default:
- fold_metrics.csv
- concurrency_comparison.csv
- feature_stability_summary.csv
- ranked_feature_table.csv
- family_importance_table.csv
- permutation_importance.csv
- strategy_library.csv
- strategy_scorecards.csv
- final_report.md
- pipeline.log

### 4.2 Checkpoint / state artifacts
These are durable and must be written safely:
- resume_state.json
- fold checkpoint files if used
- selected_thresholds.csv if needed for resume
- any partial per-fold state needed for safe restart

### 4.3 Final report artifacts
These are current-state by default unless archival is explicitly enabled:
- charts
- markdown/html/pdf reports
- best_strategy_summary.json

### 4.4 Optional archive artifacts
Only create under an explicit archive flag.

## 4. Write policy

### 4.1 Fresh run (non-resume)
At start of a fresh run:
- invalidate stale report/chart artifacts from previous runs
- overwrite current-state files as they are produced
- do not preserve old current-state files by default

### 4.2 Resume run
On resume:
- reuse only valid checkpoint/state files whose fingerprint matches
- continue overwriting current-state outputs with the latest complete state

## 5. Atomic write policy

Use write-temp-then-replace for critical files:
- resume_state.json
- fold_metrics.csv
- trade_blotter.csv
- equity_curves.csv
- selected_thresholds.csv
- final_report.md
- best_strategy_summary.json

This prevents half-written artifacts after interruption.

## 6. Logging policy

`00_logs/pipeline.log` is the single authoritative running-status file.

Defaults:
- fresh run: overwrite the prior log unless resume explicitly requests continuation semantics
- resume: append or continue intentionally, but mark the resume boundary clearly

The log must include:
- fold start/end
- purge counts
- holdout sizes
- current stage
- current seed if seed sweep active
- full fold metrics block
- IC block
- skip reasons
- checkpoint writes
- final summary

## 7. Naming policy

Use short, stable, explicit names.

Good:
- `feature_stability_summary.csv`
- `family_ablation.csv`
- `strategy_library.csv`

Bad:
- `results2.csv`
- `new_output.csv`
- `final_final_report.md`

## 8. No-run-sprawl rule

Do not create a new file for every run unless:
- it is a durable checkpoint needed for resume
- the user explicitly enables archival mode

The default user experience should be:
- one current view of the latest run
- one compact durable state area
- no uncontrolled timestamp sprawl

---

## Section B — Legacy clarifications & context

**Design goals** (from original): Clean reviewable folder structure; minimal file explosion; safe resume/checkpointing; overwrite current-state artifacts by default; optional archival only behind explicit flag.

**File-creation discipline**: Do not create one file per feature, per family, or per fold unless absolutely necessary. Prefer one cumulative CSV per output type, one report, one current-state config snapshot, one current-state resume file. Use short, explicit, sortable names (e.g. `feature_stability.csv`, `family_ablation.csv`).
