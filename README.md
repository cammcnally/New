# Swing Trading Research Pipeline

Repository: [https://github.com/cammcnally/new](https://github.com/cammcnally/new)

A walk-forward, purged/embargoed, probability-calibrated swing-trading research pipeline. It trains a stacked base-model assembly (RF, ET, XGB, LGBM, ENET), calibrates probabilities, enforces Phase 1 ranking-map guardrails, selects entry thresholds via in-train portfolio simulation, and evaluates out-of-sample with a 2-positions-per-ticker book simulator.

## Governance docs

- `docs/phase1-research-spec.md` - frozen Phase 1 metric, correction-scope, and promotion definitions
- `docs/phase1-execution-roadmap.md` - staged execution order, Phase 1 completion line, and optional Phase 2 criteria

## Local automation notes

- `AGENTS.md` and `tools/control_plane.py` are the canonical control-plane surfaces for local orchestration.
- `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/`, and `.cursor/agents/` are local compatibility shims; regenerate them with `python tools/render_cursor_projection.py` after canonical policy changes.
- `subagent/*_assessment.md` files are generated audit context and can go stale after code changes; do not treat them as authoritative runtime truth.
- When local agent tooling is used, always prefer the explicit `--output_dir` from task context over any default example.

## Control-plane environment

- Activate the repo environment with `tools/enter_e_drive_env.ps1` before running the control plane.
- Install the canonical control-plane dependencies with `pip install -r requirements-control-plane.txt -r requirements-dev.txt`.
- The control plane prefers user environment variables (`CODEX_API_KEY`, `OPENAI_API_KEY`) and only falls back to the legacy repo-local secret file at `.env/Codex_API_KEY` if those env vars are absent.
- Bootstrap the canonical policy with `.venv\Scripts\python.exe tools/control_plane.py trust-policy`, then validate with `.venv\Scripts\python.exe tools/control_plane.py validate-bootstrap`.

## Features

- **Panel input**: OHLCV + session flags; supports multiple tickers and timestamps
- **Feature engineering**: Returns, RSI, MACD, ATR, Bollinger, volume, cross-sectional z-scores, optional physics/regime block
- **Labels**: Long win/loss over a fixed horizon with ATR-based stop/target
- **Walk-forward**: Configurable outer train/test windows and purged inner CV for stacking
- **Stacking**: Out-of-fold base predictions into a calibrated meta-model (`p_cal`)
- **Ranking-map guardrails**: Empirical probability mapping records fallback usage and adjacent-fold stability, and guardrail breaches block valid-run status
- **Threshold search**: Grid over `p_min`, `theta_ev`, `theta_rel`; selection on the out-of-sample threshold holdout with threshold-family WRC metadata
- **Portfolio simulator**: Max concurrent positions, 2 positions per ticker, EV-in-R ranking, replacement exits, time exits aligned to label geometry
- **Phase 1 robustness**: Threshold-family WRC, stitched outer-test daily-return DSR, capacity diagnostics, occupancy diagnostics, and explicit promotion flags
- **Optuna** (optional): Tune RF/ET/XGB on mean inner-fold log loss with a 20-minute wall-clock cap per tunable model per fold; tuned params used in both OOF and full-train base models when enabled
- **Baseline gating**: Benchmark base-rate metrics; enable tuning only after baseline beats benchmark on a majority of folds
- **Outputs**: Fold metrics, trade blotter, equity curves, chained OOS equity, selected thresholds CSV, feature importance, markdown report, JSON config/metrics

## Label and simulator behavior

- Entry at next open; stop/target checked bar-by-bar.
- If stop and target are both hit on the same bar, the outcome is treated as a **stop-first** (loss). This is conservative and consistent between labeling and portfolio simulation.

## Requirements

- Python 3.12.10 - single source of truth: `.python-version`; `pyproject.toml` enforces `requires-python >=3.12.10,<3.13` for tooling
- Use the workspace virtual environment interpreter for canonical runs: `.venv\Scripts\python.exe`
- See `requirements.txt` (pandas, pandas-stubs, numpy, matplotlib, scikit-learn, xgboost, lightgbm, tabulate, optuna)

```bash
pip install -r requirements.txt
```

## Input

- **Panel CSV**: `panel_ohlcv_clean.csv` (or path via `--input_panel_csv`) with columns: `ticker`, `timestamp_utc`, `open`, `high`, `low`, `close`, `volume`, `is_incomplete_session`.

## Output location (E: drive)

All pipeline artifacts (logs, metrics, state, reports) are saved to the E: drive under `E:\stock_csvs_AI-Perspective`. Paths resolve relative to `E:\stock_csvs_AI-Perspective\NEW`. Override via env `PIPELINE_BASE_PATH` if the repo is elsewhere. Run from project root.

## Usage

All outputs (log, metrics, state) go under `--output_dir`. Use the same `output_dir` for run and resume.

Suggested values:

- `pipeline_outputs` for the final decision-grade run
- `pipeline_outputs_smoke` for overwrite-oriented smoke ladder runs
- `pipeline_outputs_repro` for the canonical deterministic rerun
- `pipeline_outputs_optuna` for optional post-baseline tuning

**Decision-grade baseline (no tuning)** - run first and confirm fold metrics, robustness fields, ranking-map guardrails, and promotion logic:

```powershell
.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir {output_dir}
```

Set `{output_dir}` to `pipeline_outputs` for the canonical decision-grade run.

**With Optuna tuning** - only after baseline looks good (for example `test_log_loss` / `test_brier` beat benchmark on most folds):

```powershell
.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir {output_dir} `
  --enable_optuna_tuning
```

Set `{output_dir}` to `pipeline_outputs_optuna` for the optional post-baseline tuning run.

**Smoke ladder** - use a separate overwrite-oriented directory so smoke artifacts never mix with the canonical run:

```powershell
.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir {output_dir}
```

Set `{output_dir}` to `pipeline_outputs_smoke` for the smoke ladder.

**Canonical reproducibility rerun** - only after the full Phase 1 run is stable:

```powershell
.venv\Scripts\python.exe Pipeline.py `
  --input_panel_csv panel_ohlcv_clean.csv `
  --output_dir {output_dir} `
  --deterministic_mode
```

Set `{output_dir}` to `pipeline_outputs_repro` for the canonical reproducibility rerun.

**Other options**

- `--output_dir` - directory for all outputs (required); log at `{output_dir}/00_logs/pipeline.log`
- `--no_physics_block` - exclude physics/regime features
- `--starting_capital`, `--risk_per_trade` - simulation parameters
- `--resume` - resume from `{output_dir}/06_state/resume_state.json` using the same input and `output_dir`

**Note:** The pipeline writes `pipeline.log` itself to `{output_dir}/00_logs/pipeline.log`. Do not redirect stdout to that file, or progress output from libraries can corrupt the log with whitespace.

## Outputs (numbered tree under `output_dir`)

The pipeline writes to numbered subdirectories. `00_logs/pipeline.log` is the authoritative run log and `06_state/resume_state.json` is the only resume checkpoint surface.

| Dir | File | Description |
|-----|------|-------------|
| `00_logs/` | `pipeline.log` | Run log (authoritative) |
| `00_logs/` | `panel_timestamp_regularity_summary.json` | Per-ticker vs global timestamp coverage summary |
| `00_logs/` | `panel_timestamp_regularity_by_ticker.csv` | Per-ticker coverage (for embargo/split diagnostics) |
| `01_data/` | `model_ready_dataset.csv` | Labeled panel after feature and label construction |
| `02_metrics/` | `fold_metrics.csv` | Per-fold, per-concurrency metrics and diagnostics, including ranking-map guardrail evidence |
| `02_metrics/` | `trade_blotter.csv` | All simulated trades |
| `02_metrics/` | `equity_curves.csv` | Per-fold, per-concurrency equity series |
| `02_metrics/` | `selected_thresholds.csv` | Chosen (`p_min`, `theta_ev`, `theta_rel`) per fold and concurrency |
| `02_metrics/` | `concurrency_comparison.csv` | Aggregates by `max_concurrent` |
| `02_metrics/` | `threshold_candidate_diagnostics.csv` | One row per fold and threshold tuple with WRC metadata |
| `02_metrics/` | `policy_daily_returns.csv` | Stitched calendar-day strategy return series with skipped folds retained as zero-return windows |
| `02_metrics/` | `overall_metrics.json` | OOS metrics for best concurrency, including run-level ranking-map guardrail status |
| `03_features/` | `feature_registry.csv` | Feature registry and coverage |
| `03_features/` | `feature_registry_coverage_summary.csv` | Registry coverage counts by family/type |
| `03_features/` | `feature_validation_rows.csv` | Raw fold-level feature-validation rows |
| `03_features/` | `feature_validation_ic_daily_rows.csv` | Raw daily IC rows used for feature-validation aggregation |
| `03_features/` | `feature_validation_report.csv` | Fold-aggregated OOS feature-validation diagnostics |
| `03_features/` | `feature_importances_by_fold.csv` | Base-model feature importance by fold |
| `03_features/` | `feature_stability_summary.csv` | Cross-fold importance summary |
| `04_strategies/` | `strategy_library.csv` | Final strategy summary table |
| `04_strategies/` | `strategy_scorecards.csv` | Scorecard defaults and promotion-support view |
| `04_strategies/` | `model_comparison_report_rows.csv` | Raw fold-level model-comparison rows |
| `04_strategies/` | `model_comparison_report.csv` | OOS comparison versus simpler baseline assemblies |
| `04_strategies/` | `position_ranking_audit.csv` | Deterministic ranking / clip / skip audit trail |
| `04_strategies/` | `best_strategy_summary.json` | Best strategy summary |
| `04_strategies/` | `seed_robustness_summary.csv` | Seed-sensitivity summary for the shortlisted strategy |
| `05_reports/` | `equity_curve_best_concurrency.png` | Chart of chained OOS equity for best concurrency |
| `05_reports/` | `final_report.md` | Markdown summary report |
| `06_state/` | `resume_state.json` | Checkpoint for resume at `{output_dir}/06_state/resume_state.json` |
| `06_state/` | `config_snapshot.json` | Pipeline config used |
| `06_state/` | `verification.json` | Input panel checks and run-level verification state |

## License

Use and modify as needed for research.
