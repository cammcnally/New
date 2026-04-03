# phase1-sanity-check

Local compatibility shim for the canonical `phase1_sanity_check` action in `AGENTS.md`.

Required artifact surfaces:

- `02_metrics/overall_metrics.json`
- `02_metrics/fold_metrics.csv`
- `02_metrics/threshold_candidate_diagnostics.csv`
- `02_metrics/policy_daily_returns.csv`
- `03_features/feature_validation_report.csv`
- `04_strategies/best_strategy_summary.json`
- `04_strategies/model_comparison_report.csv`
- `04_strategies/position_ranking_audit.csv`
- `04_strategies/strategy_scorecards.csv`
- `05_reports/final_report.md`
- `06_state/resume_state.json`

Canonical path contract:

- log: `{output_dir}/00_logs/pipeline.log`
- resume: `{output_dir}/06_state/resume_state.json`
