# Validation and Acceptance Plan

> **This master file supersedes both prior versions. On conflict, Section A governs.**

## 1. Build acceptance criteria

The implementation is acceptable only if all of the following are true:

1. `Pipeline.py` remains the main pipeline file
2. Feature registry includes at least 70 regular + 20 physics/regime features
3. Volatility-clustering family exists and is reported separately
4. Feature discovery is staged, not raw-importance-only
5. Orthogonality / redundancy handling exists
6. Threshold selection is out-of-sample
7. Calibration is chronologically later than meta training
8. Spearman IC is implemented
9. Seed-robustness evaluation exists
10. Strategy library output exists
11. Final report exists and is human-readable
12. Outputs are clean, ordered, and overwrite-oriented
13. Resume / checkpoint logic is robust
14. No placeholders / mock metrics / scaffold-only outputs remain

## 2. Implementation authenticity checks

Reject the build if any of these are present:
- random stand-ins for labels, probabilities, or strategy metrics
- mocked strategy outputs
- commented-out core execution stages
- unimplemented “TODO” blocks covering core methodology
- claims of completeness without an end-to-end runnable path

## 3. Methodology checks

### Chronology checks
- signal time, entry time, and event-resolution time are explicit
- outer-boundary purge is enforced
- threshold-fit purge is enforced
- calibration holdout is chronologically later than meta-fit
- no in-sample threshold selection path remains

### Validation checks
- inner purged CV is still event-aware
- threshold holdout is scored out-of-sample
- final test is scored out-of-sample
- folds with invalid split geometry are skipped explicitly

### Calibration checks
- calibrator is not fit on rows used to fit the meta model
- calibration holdout viability thresholds are enforced
- sigmoid vs isotonic choice follows explicit data-size rules
- no neutral-probability fallback is used for invalid calibration folds

### Train-only transformation checks
The following must be verifiably fit on train-only data within the relevant fold stage:
- correlation / orthogonality pruning
- family ranking
- ablation ranking
- subset search
- any label-aware transform

## 4. Feature-discovery checks

- registry present and complete
- family tags present
- volatility-clustering family present
- raw model importance output exists
- permutation importance output exists
- fold stability output exists
- family contribution output exists
- ablation output exists
- selected final feature set exists
- rejected / unstable feature list exists
- regime-specific feature output exists

## 5. IC and ranking-quality checks

- Spearman IC is computed against realized R-multiple
- Spearman IC is computed against forward return
- mean IC reported
- IC std reported
- IC hit rate reported
- ICIR reported
- IC logic is chronology-safe
- if cross-sectional timestamp IC is used, it handles low-candidate timestamps safely

## 6. Seed-robustness checks

- seed mode exists
- research seed list exists
- final shortlist seed list exists
- seed sweeps are staged, not applied blindly to every stage
- seed_robustness_summary.csv exists
- shortlisted strategies report mean/std PF, Calmar, expectancy_r, CAGR, and MDD across seeds

## 7. Strategy-library checks

- strategy library exists
- each row is scored with portfolio metrics
- hard gates are applied
- family concentration is visible
- positive-fold ratio is visible
- churn is visible
- top-ticker concentration is visible
- ranking order follows the documented priority stack

## 8. Logging checks

`pipeline.log` must show:
- fold start / end
- purge counts
- threshold-holdout and calibration-holdout sizes
- current stage
- current seed when seed sweep active
- full fold metrics summary block
- IC summary block
- skip reasons
- checkpoint writes
- final overall summary

## 9. File-hygiene checks

- numbered folders exist
- filenames are clean and stable
- current-state files overwrite cleanly
- critical files use atomic writes
- stale reports/charts are invalidated on fresh non-resume runs
- no uncontrolled timestamp sprawl
- archive is optional, not default

## 10. Smoke test / runbook

At minimum, verify:
1. fresh run
2. interrupted run + resume
3. fold skip due to degenerate threshold holdout
4. fold skip due to degenerate calibration holdout
5. seed-robustness run on shortlisted candidates
6. full output regeneration
7. audit subagent regeneration of `subagent/pipeline-auditor_assessment.md`

## 11. Final report checks

The final report must include:
- complete feature list in English
- family grouping
- settings / lookbacks
- survivor / rejection rationale
- volatility-clustering explanation
- Spearman IC explanation
- seed-robustness explanation
- strategy-library summary
- explanation of entry/exit/ranking/risk logic in human-readable terms
- explicit note that ensemble logic is not automatically a simple crossover rule

## 12. Final sign-off standard

Do not consider the task complete until:
- the build is implemented
- the outputs are generated cleanly
- the audit can be rerun cleanly
- the report and strategy library are reviewable without digging through dozens of files
- there are no placeholders, mock results, or scaffold-only claims left in the repo
