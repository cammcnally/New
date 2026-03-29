---
name: phase1-validation-runbook
description: Decision-grade validation workflow for Phase 1 research and artifact review.
---

Use this skill when the task is to validate a completed run, a smoke tier, or a deterministic rerun.

Required workflow:
1. Check that the run completed without unresolved blocker.
2. Inspect:
   - `02_metrics/overall_metrics.json`
   - `02_metrics/fold_metrics.csv`
   - `02_metrics/threshold_candidate_diagnostics.csv`
   - `02_metrics/policy_daily_returns.csv`
   - `03_features/feature_validation_report.csv`
   - `04_strategies/model_comparison_report.csv`
   - `04_strategies/position_ranking_audit.csv`
   - `04_strategies/strategy_scorecards.csv`
   - `05_reports/final_report.md`
   - `06_state/resume_state.json`
3. Confirm:
   - ranking-map guardrails did not invalidate the run
   - WRC status and p-values are populated where required
   - skipped folds remain present as zero-return windows in stitched daily returns
   - occupancy is reported but not treated as a target
   - promotion flags match the frozen hierarchy
4. Report:
   - pass / fail
   - exact blocker
   - exact artifact path
   - whether result is decision-grade, smoke-only, or reproducibility-only
