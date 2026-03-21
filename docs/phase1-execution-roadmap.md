# Phase 1 Execution Roadmap

## Why this file exists

This file is the durable handoff for future work. It is meant to prevent drift, hidden redefinition, and accidental reordering of work.

The governing order is:

1. behavioral correctness
2. statistical validation
3. refactoring

Do not reverse that order.

## Completion boundary

The project has two possible finish lines, but only one is required.

### Required finish line

Phase 1 behavioral/statistical completion is the true required finish line.

If the pipeline is behaviorally correct, statistically governed, reproducible, tested, and decision-grade, the project is considered complete even if `Pipeline.py` remains large.

### Optional finish line

Phase 2 is an optional auditability refactor. It exists to improve diagnosis, traceability, contributor safety, and future extension speed. It is not required for the project to count as complete.

## Required read order for future sessions

Before editing code:

1. read `docs/phase1-research-spec.md`
2. read this roadmap
3. inspect the latest `02_metrics/overall_metrics.json` and `05_reports/final_report.md` if they exist

## Current status snapshot

As of this checkpoint:

- fixed max concurrent behavior is implemented as a cap of `8`
- threshold-family correction is implemented for the 108 threshold tuples only
- stitched calendar-day outer-test validation is implemented
- WRC, DSR, occupancy, turnover, holding-period, capacity, and regime-policy fields are wired into outputs
- resume/version fields are wired into artifacts
- a full decision-grade end-to-end validation run has not yet been completed
- automated tests have not yet been added
- feature validation, model comparison, scorecard defaults, canonical reproducibility mode, and cache policy still need to be closed out

## Stage tracker

### Stage 0 - Freeze spec

Status: `done`

Deliverables:

- `docs/phase1-research-spec.md`
- this roadmap

### Stage 1 - Data / label integrity

Status: `partial`

Already in place:

- chronological outer folds
- outer-boundary purging
- purged inner CV
- threshold holdout separation
- calibration holdout separation
- coarse costs and slippage

Still to tighten:

- explicit assertions for no forward liquidity leakage
- explicit assertions for no hidden universe leakage
- explicit cost-model snapshot validation
- explicit validation memo for feature/label/liquidity timing

### Stage 2 - Feature registry

Status: `partial`

Already in place:

- feature registry exists
- family/group metadata exists

Still to add:

- formula
- timestamping rule
- economic thesis
- expected sign
- expected decay horizon

No anonymous feature should be promoted once this stage is complete.

### Stage 3 - Feature validation

Status: `pending`

Needed output:

- `03_features/feature_validation_report.csv`

Core checks to add:

- OOS cross-sectional Spearman IC
- HAC t-stat
- sign stability across folds
- regime stability
- monotonicity by decile
- incremental lift after costs
- explicit `insufficient_data` status where required

### Stage 4 - Model assembly

Status: `pending`

Needed output:

- `04_strategies/model_comparison_report.csv`

Required comparisons:

- simple linear baseline
- equal-weight rank blend
- incumbent ML stack

ML promotion should remain strictly OOS and must beat simpler baselines economically, not just statistically.

### Stage 5 - Strategy construction

Status: `mostly_done`

Already in place:

- fixed cap of 8
- no target occupancy
- threshold family materialization
- deterministic ranking path
- lagged-liquidity capacity clipping/skipping
- threshold candidate diagnostics

Still to add or review:

- dedicated `position_ranking_audit.csv`
- implementation-status / verification-stage fields in outputs
- deterministic cache policy and canonical rerun comparisons

### Stage 6 - Robustness and execution realism

Status: `mostly_done`

Already in place:

- daily-return basis
- adjusted daily Sharpe
- threshold-family WRC
- stitched outer-test DSR
- fold skip rules
- turnover metrics
- holding-period metrics
- capacity diagnostics
- regime-policy diagnostics
- promotion flags and reasons

Still to add or review:

- Sortino and scorecard-default reporting
- power/sufficiency behavior of WRC on real runs
- expected-R mapping stability on thin-support folds
- capacity headroom and capacity-drag thresholds
- canonical reproducibility mode

### Stage 7 - Tests

Status: `pending`

Test order:

1. pure helper tests
2. rule/regression tests
3. smoke tests

Minimum helper tests:

- daily-return aggregation
- adjusted Sharpe
- DSR
- WRC moving-block bootstrap
- expected-R mapping
- stitched-series construction
- cross-sectional IC construction
- cost-model schema validation

Minimum rule/smoke tests:

- `max_concurrent = 8` only
- occupancy not rewarded
- skipped folds stay in calendar as zero-return windows
- stale resume/schema mismatch rejected
- WRC failure suppresses promotion
- non-positive DSR blocks promotion
- capacity uses lagged fields only
- canonical rerun reproduces outputs with caches disabled

## Ordered next actions

1. add the remaining frozen-spec fields to docs and code paths
2. implement feature validation, scorecard defaults, cost-model schema, and model comparison
3. add helper, regression, and smoke tests
4. run Tier 1 and Tier 2 smoke and only then mark `smoke_validated`
5. run Tier 3 preproduction smoke and inspect artifact completeness
6. run the final Phase 1 decision-grade rerun
7. run a canonical reproducibility rerun with deterministic settings and caches disabled
8. only if Phase 1 is stable and refactoring would materially improve diagnosis or safe extension, consider a Phase 2 auditability refactor

## Smoke ladder

`pipeline_outputs_smoke` is overwrite-oriented and should be cleared before each tier.

### Tier 1 - plumbing

- tickers: `AMD`, `MSFT`, `CAT`, `RTX`
- history: 18 months
- reduced smoke config:
  - `outer_train_months = 6`
  - `outer_test_months = 2`
  - `threshold_holdout_months = 1`
  - `calibration_holdout_months = 1`
  - `inner_folds = 2`
- required checks:
  - run completes
  - artifacts written
  - no schema errors

### Tier 2 - behavior sanity

- tickers: `AMD`, `MSFT`, `CAT`, `RTX`, `AMAT`, `CSCO`, `MU`, `LRCX`
- history: `2016-01-01` onward
- canonical Phase 1 config
- required checks:
  - WRC runs
  - skip logic runs
  - stitched OOS exists
  - occupancy / capacity / turnover metrics are populated

### Tier 3 - preproduction

- tickers: all available tickers in `panel_ohlcv_clean.csv`
- history: `2018-01-01` onward
- canonical Phase 1 config
- required checks:
  - promotion logic exercised
  - scorecard populated
  - required artifacts are complete

### Final decision-grade run

- all available tickers
- full available history
- canonical Phase 1 config

### Canonical reproducibility rerun

- same data scope as final run
- deterministic single-thread settings
- caches cleared and disabled

## Definition of Phase 1 completion

Phase 1 is complete only when all of the following are true:

- pipeline runs end-to-end with fixed-8 cap behavior
- required artifacts are populated deterministically
- tests pass
- report states scope boundaries narrowly and correctly
- strategy either passes or fails promotion under the new rules
- result is reproducible from a clean canonical rerun

If all of the above are true, the project is considered complete for research and governance purposes.

## Definition of optional Phase 2 start

Phase 2 should be considered only after Phase 1 completion. Its job is auditability-first structural cleanup, not behavior change.

Phase 2 is justified only if one or more of these are true:

- debugging is repeatedly slowed by single-file coupling
- tests are harder to add or maintain because logic is too entangled
- future feature/model/robustness work is risky because boundaries are unclear
- multiple contributors or agents need cleaner ownership boundaries

Planned Phase 2 themes:

- preferred extraction order:
  - metrics and robustness helpers
  - stitched-series and promotion logic
  - execution and capacity logic
  - reporting and artifact schema builders
- keep any extraction behavior-preserving
- do not combine broad layout cleanup with research-method changes
- do not require full repo modularization by default
- a lighter refactor is acceptable if it delivers most of the diagnostic value

## Anti-drift rules

- do not broaden claims beyond threshold-family correction
- do not refactor for cleanliness before tests and validation are stable
- do not treat Phase 2 as automatic project completion work
- do not change frozen metrics without updating `docs/phase1-research-spec.md`
- do not treat `8` as a target occupancy
- do not interpret portfolio-policy gates as equivalent to statistical validity
