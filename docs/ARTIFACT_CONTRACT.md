# Artifact Contract

Every important experiment or strategy run should emit a deterministic artifact bundle.

This document is cross-cutting. It does not replace [docs/data_contract.md](e:\stock_csvs_AI-Perspective\NEW\docs\data_contract.md), which remains the authority for market-data surfaces and schema semantics.

For the broader post-Phase-1 downstream architecture that motivates richer artifact and reporting requirements, also see `docs/end_to_end_trading_system_architecture.md`.

## Minimum fields for a run

- strategy_name
- run_id
- created_at_utc
- git_commit
- data_snapshot_id
- model_version
- benchmark_id
- risk_free_source
- config_path or config_hash
- summary_metrics artifact
- report artifact
- validation artifact

## Canonical outputs

- summary_metrics.json
- metrics_detail.parquet
- equity_curve_daily.parquet
- validation_folds.parquet
- model_metadata.json
- manifest.json
- charts/
- strategy_report.html

## Repo expectations

- Artifacts must be deterministic for the same inputs and config.
- Manifest files must advertise benchmark and risk-free context explicitly.
- Downstream reports should consume canonical artifacts rather than rebuilding semantics ad hoc.
- Notebook-only outputs are insufficient for core research or strategy decisions.
