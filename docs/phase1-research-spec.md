# Phase 1 Research Spec

## Purpose

This file freezes the Phase 1 definitions for the swing-trading research pipeline so runs remain comparable while implementation, testing, and validation continue.

Phase 1 is intentionally narrower than full-pipeline research correction. It freezes threshold-family correction, stitched outer-test validation, and promotion rules without claiming full correction for upstream feature/model/research-path search.

Phase 2, if it happens later, is an optional auditability refactor and is not part of required research completion.

## Versioned scope

- `schema_version = 2.0.0`
- `robustness_method_version = phase1_threshold_wrc_nw_v1`
- `search_family_definition_version = threshold_policy_family_v1`
- `threshold_search_corrected = true`
- `full_pipeline_corrected = false`
- `trial_scope_formal = threshold_policy_search_only`

Any future change to the items below must update this file first, then the version fields.

## Fixed portfolio behavior

- `max_concurrent = 8` is a hard cap only.
- Occupancy is diagnostic only.
- The pipeline must not reward full slot usage or penalize unused capacity.

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

- run White’s Reality Check on the threshold-holdout daily return matrix for the 108-tuple threshold family
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
