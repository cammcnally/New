# Phase 1 Research Spec

## Purpose

This file freezes the Phase 1 definitions for the swing-trading research pipeline so runs remain comparable while implementation, testing, and validation continue.

Phase 1 is intentionally narrower than full-pipeline research correction. It freezes threshold-family correction, stitched outer-test validation, promotion rules, and scorecard defaults without claiming full correction for upstream feature, model, or research-path search.

Phase 2, if it happens later, is an optional auditability refactor and is not part of required research completion.

## Versioned scope

- `schema_version = 2.1.0`
- `robustness_method_version = phase1_threshold_wrc_nw_v2`
- `search_family_definition_version = threshold_policy_family_v1`
- `threshold_search_corrected = true`
- `full_pipeline_corrected = false`
- `trial_scope_formal = threshold_policy_search_only`
- `scorecard_label = scorecard_default_thresholds_v1`
- `scorecard_archetype = concentrated_multi_day_strategy_max8`

Any future change to the items below must update this file first, then the version fields.

## Verification language

Allowed implementation-status values:

- `planned`
- `present`
- `unit_tested`
- `smoke_validated`
- `reproducible_verified`

Rules:

- never use the word "verified" in reports or summaries unless `implementation_status = reproducible_verified`
- `present` means the code path exists only
- `smoke_validated` requires Tier 1 and Tier 2 smoke success
- `reproducible_verified` requires a clean canonical rerun match

Major artifacts should carry:

- `implementation_status`
- `verification_stage_reached`

## Fixed portfolio behavior

- `max_concurrent = 8` is a hard cap only
- occupancy is diagnostic only
- the pipeline must not reward full slot usage or penalize unused capacity

## Frozen daily return construction

Hard-gate robustness statistics use calendar-day arithmetic daily returns derived from end-of-day marked portfolio equity.

Implementation rules:

- use end-of-day marked portfolio equity
- use arithmetic daily returns
- include idle-capital trading days as zero-return days
- book costs and slippage on the day they occur
- mark open positions daily using the same price convention as the equity curve
- preserve the trading calendar only; weekends and holidays do not create extra observations

## Frozen adjusted Sharpe definition

Phase 1 uses a single adjusted Sharpe estimator:

- estimator: Newey-West HAC-adjusted Sharpe
- input: calendar-day arithmetic daily returns
- annualization: `sqrt(252)`
- lag rule: `L = min(5, floor(T^(1/4)))`

Reporting requirements:

- report `sharpe_daily_raw`
- report `adjusted_sharpe_daily`
- only `adjusted_sharpe_daily` feeds formal Phase 1 robustness reporting

## Frozen threshold search family

The corrected family is exactly the 108 threshold tuples:

- `p_min_grid`: 9 values
- `theta_ev_grid`: 4 values
- `theta_rel_grid`: 3 values
- total family size: `9 * 4 * 3 = 108`

A threshold-family candidate is defined as:

`threshold tuple + fixed ranking spec + fixed execution rules + fixed cost model + fixed capacity rules + fixed portfolio construction rules`

Anything outside that definition is not corrected by Phase 1.

## Frozen fold-local WRC procedure

Within each fold:

- run White's Reality Check on the threshold-holdout daily return matrix for the 108-tuple threshold family
- bootstrap: moving-block bootstrap
- default block length: `5`
- persist bootstrap reps, seed, and block length

Minimum sufficiency rules:

- at least `60` daily observations
- at least `20` nonzero-return days
- at least `20` closed trades
- average active exposure above the configured floor

If sufficiency fails:

- set `wrc_status = insufficient_data`
- do not silently convert insufficient data into pass/fail

Fold promotion rule:

- `fold_selected = true` only if sufficiency passes and `wrc_pvalue <= 0.10`
- otherwise `fold_selected = false`
- `fold_skip_reason` must be `wrc_fail` or `insufficient_data`

## Frozen stitched outer-test rules

Strategy-level confirmation uses stitched outer-test calendar-day returns.

Stitching rules:

- preserve the original outer-test calendar
- skipped folds contribute zero returns during their outer-test windows
- do not drop dates from skipped windows
- gaps or overlaps are not allowed

This stitched series is the only basis for:

- final adjusted Sharpe
- final deflated Sharpe
- stitched drawdown
- stitched Calmar

## Frozen deflated Sharpe reporting

Phase 1 DSR is computed on stitched outer-test daily returns using:

- Sharpe input: `adjusted_sharpe_daily`
- formal trial count: `108`
- trial scope: `threshold_policy_search_only`

Phase 1 reporting must always include:

- `threshold_search_corrected = true`
- `full_pipeline_corrected = false`
- `trial_count_formal = 108`
- `trial_scope_formal = threshold_policy_search_only`

## Feature-validation definitions

Feature validation remains informative and governance-oriented in Phase 1. It does not expand the formal multiple-testing correction boundary.

- IC metric: `cross_sectional_spearman_daily`
- label return: `forward_net_arithmetic_return_over_label_horizon`
- `min_assets_per_day = min(20, ceil(0.70 * panel_asset_count))`
- `min_ic_days_per_fold = 60`
- winsorize feature values at `[0.005, 0.995]`
- t-stat method: Newey-West HAC with `L = min(5, floor(T^(1/4)))`
- research sign-stability threshold: `0.60`
- preferred sign-stability threshold: `0.70`
- regime stability: at least `2` positive core regimes out of `3`, with `40` minimum regime days
- monotonicity buckets: `10`
- monotonicity gate:
  - top-minus-bottom spread must be positive
  - top-minus-bottom t-stat must be at least `2.0`
  - adjacent bucket ordering fraction must be at least `0.70`
- incremental lift is measured net of modeled costs and must be positive
- feature-promotion thresholds:
  - research minimum t-stat: `2.0`
  - preferred t-stat: `3.0`

## Model-comparison definitions

Model comparison must use the same purged/embargoed splits and the same downstream policy layer for every contender.

Contenders:

- `baseline_linear`
- `baseline_equal_weight_rank_blend`
- `incumbent_ml`

Rules:

- default Phase 1 mode is untuned
- bounded tuning, if explicitly enabled:
  - max Optuna trials per tunable model per fold: `20`
  - max wall-clock minutes per tunable model per fold: `20`
  - random seeds per model: `1`
  - fixed seed: `42`
- no manual feature-subset changes during comparison
- primary comparison metric: `adjusted_oos_sharpe`
- secondary comparison metric: `net_oos_spread_after_costs`
- ML promotion requires at least `10%` primary-metric improvement or materially lower drawdown, turnover, or capacity drag

## Ranking-map guardrails

- map type: isotonic non-decreasing
- fit scope: fold-local fit only
- diagnostics buckets: `10`
- `min_total_fit_samples = 300`
- `min_samples_per_bucket = 30`
- fallback mode: deterministic simple rank
- fallback if:
  - total fit samples below minimum
  - any bucket sample count below minimum
- stability checks:
  - minimum adjacent-fold Spearman of bucket scores: `0.70`
  - maximum fallback-usage fraction per fold: `0.25`
  - top 2 buckets positive fraction must be at least `0.60`

## Frozen promotion hierarchy

Final promotion is hierarchical.

### A. Statistical validity

`robustness_pass = true` only if:

- `deflated_sharpe_daily > 0`
- no leakage violations
- no unresolved capacity-rule violations
- sufficient stitched OOS daily observations

### B. Implementation realism

Implementation realism remains part of the must-pass path:

- lagged-liquidity-only capacity checks
- deterministic clip/skip behavior
- no forward liquidity information

### C. Portfolio policy

`portfolio_policy_pass = true` only if:

- `calmar >= 0.75`
- `max_drawdown <= 0.25`
- `expectancy_r > 0`
- `regime_diversity_policy_pass = true`

Final decision:

- `promotion_pass = robustness_pass AND portfolio_policy_pass`

## Evidence hierarchy

- `feature_validation_pass` is necessary, not sufficient
- `model_comparison_pass` is necessary, not sufficient
- only strategy-level stitched OOS results determine `promotion_pass`

## Fold-threshold defaults

- `research_positive_fold_fraction_min = 0.60`
- `preferred_positive_fold_fraction_min = 0.70`
- `live_positive_fold_fraction_min = 0.60`
- `allocation_positive_fold_fraction_min = 0.67`

## Cost-model schema

The effective cost model must define:

- `commission_per_side`
- `slippage_per_side`
- `spread_source`
- `borrow_or_financing_rate`
- `reject_or_clip_penalty`
- `idle_cash_treatment`

Measurement basis:

- commissions: per fill
- slippage: per side
- financing: daily accrual
- reject/clip effects: explicit PnL impact
- idle cash: included in daily equity

Phase 1 run validity requires every field to be populated in the effective model snapshot.

## Scorecard defaults

These are default thresholds for the current strategy archetype, not universal truths.

### Research viable

- adjusted OOS Sharpe `>= 0.75`
- profit factor `>= 1.20`
- Sortino `>= 1.00`
- Calmar `>= 0.50`
- max drawdown `<= 0.25`
- DSR `> 0.0`
- gross edge / round-trip cost `>= 2.0`
- closed trades `>= 100`
- nonzero-return days `>= 100`
- positive fold fraction `>= 0.60`
- calendar days `>= 126`

### Live-pilot viable

- adjusted OOS Sharpe `>= 1.00`
- profit factor `>= 1.25`
- Sortino `>= 1.50`
- Calmar `>= 0.75`
- max drawdown `<= 0.20`
- DSR `> 0.0`
- gross edge / round-trip cost `>= 3.0`
- closed trades `>= 150`
- nonzero-return days `>= 150`
- positive fold fraction `>= 0.60`
- positive regimes `>= 2 / 3`
- single-regime PnL fraction `<= 0.60`
- calendar days `>= 252`

### Allocation-ready

- adjusted OOS Sharpe `>= 1.25`
- profit factor `>= 1.40`
- Sortino `>= 1.75`
- Calmar `>= 1.00`
- max drawdown `<= 0.15`
- DSR `> 0.0`
- gross edge / round-trip cost `>= 4.0`
- closed trades `>= 250`
- nonzero-return days `>= 250`
- positive fold fraction `>= 0.67`
- calendar days `>= 504`
- decay haircut range `[0.30, 0.50]`

## Reproducibility mode

Canonical reproducibility verification requires:

- deterministic mode enabled
- `random_seed = 42`
- single-seed mode
- single-thread execution for canonical reruns
- caches cleared before canonical run
- caches disabled for the canonical rerun

Comparison tolerances:

- discrete fields: exact match
- float absolute tolerance: `1e-8`
- float relative tolerance: `1e-6`
- time-series absolute tolerance: `1e-8`

Do not claim `reproducible_verified` if canonical settings were not used.

## Cache policy

- cache scope: run-local only
- cache location: `output_dir/cache/`
- cache keys must include:
  - input-data hash
  - code fingerprint
  - schema version
  - robustness-method version
  - search-family-definition version
  - config hash
- canonical outputs must reproduce with caches cleared
- caches must never be required to generate canonical outputs

## Frozen claim boundary

Phase 1 does not claim:

- full multiple-testing correction for feature discovery
- full correction for model-family selection
- full correction for ranking-spec search
- full correction for regime-taxonomy selection

The strongest allowed claim is:

> Phase 1 provides within-family correction for threshold-policy search plus stitched outer-test confirmation for the selected adaptive deployment policy.

## Required artifact fields

All major artifacts and resume state must carry:

- `schema_version`
- `robustness_method_version`
- `search_family_definition_version`
- `implementation_status`
- `verification_stage_reached`

Strategy and metrics artifacts must also carry:

- `threshold_search_corrected`
- `full_pipeline_corrected`
- `trial_scope_formal`
- `trial_count_formal`

## Work-order rule

Before any further work:

1. update this file if a frozen definition must change
2. bump the relevant version fields
3. only then change implementation or tests
