# Swing Trading Research Pipeline

Repository: [https://github.com/cammcnally/new](https://github.com/cammcnally/new)

A walk-forward, purged/embargoed, probability-calibrated swing-trading research pipeline. It trains stacked classifiers (RF, ET, XGB) with optional Optuna hyperparameter tuning, selects entry thresholds via in-train portfolio simulation, and evaluates out-of-sample with a 2-positions-per-ticker book simulator.

## Governance docs

- `docs/phase1-research-spec.md` — frozen Phase 1 metric, correction-scope, and promotion definitions
- `docs/phase1-execution-roadmap.md` — staged execution order, Phase 1 completion line, and optional Phase 2 criteria

## Features

- **Panel input**: OHLCV + session flags; supports multiple tickers and timestamps
- **Feature engineering**: Returns, RSI, MACD, ATR, Bollinger, volume, cross-sectional z-scores, optional physics/regime block
- **Labels**: Long win/loss over a fixed horizon with ATR-based stop/target
- **Walk-forward**: Configurable outer train/test windows and purged inner CV for stacking
- **Stacking**: Out-of-fold base predictions → logistic meta → Platt-scaled probabilities (`p_cal`)
- **Threshold search**: Grid over `p_min`, `theta_ev`, `theta_rel`; selection by `research_score()` (Calmar, profit factor, expectancy, stability, churn)
- **Portfolio simulator**: Max concurrent positions, 2 positions per ticker, EV-in-R ranking, replacement exits, time exits aligned to label geometry
- **Phase 1 robustness**: Threshold-family WRC, stitched outer-test daily-return DSR, capacity diagnostics, occupancy diagnostics, and explicit promotion flags
- **Optuna** (optional): Tune RF/ET/XGB on mean inner-fold log loss; tuned params used in both OOF and full-train base models when enabled
- **Baseline gating**: Benchmark base-rate metrics; enable tuning only after baseline beats benchmark on a majority of folds
- **Outputs**: Fold metrics, trade blotter, equity curves, chained OOS equity, selected thresholds CSV, feature importance, markdown report, JSON config/metrics

## Label and simulator behavior

- Entry at next open; stop/target checked bar-by-bar.
- If stop and target are both hit on the same bar, the outcome is treated as a **stop-first** (loss). This is conservative and consistent between labeling and portfolio simulation.

## Requirements

- Python 3.8+
- See `requirements.txt` (pandas, pandas-stubs, numpy, matplotlib, scikit-learn, xgboost, lightgbm, tabulate, optuna)

```bash
pip install -r requirements.txt
```

## Input

- **Panel CSV**: `panel_ohlcv_clean.csv` (or path via `--input_panel_csv`) with columns: `ticker`, `timestamp_utc`, `open`, `high`, `low`, `close`, `volume`, `is_incomplete_session`.

## Output location (E: drive)

All pipeline artifacts (logs, metrics, state, reports) are saved to the E: drive under `E:\stock_csvs_AI-Perspective`. Paths resolve relative to `E:\stock_csvs_AI-Perspective\NEW`. Override via env `PIPELINE_BASE_PATH` if the repo is elsewhere. Run from project root.

## Usage

All outputs (log, metrics, state) go under `--output_dir`. Use the same `output_dir` for run and resume. Common values: `pipeline_outputs` (all runs), `pipeline_outputs_optuna` (Optuna tuning). Use `pipeline_outputs` for both baseline and quick validation runs.

**Baseline (no tuning)** — run first and confirm fold metrics and benchmark pass:

```bash
python Pipeline.py \
  --input_panel_csv panel_ohlcv_clean.csv \
  --output_dir pipeline_outputs
```

**With Optuna tuning** — only after baseline looks good (e.g. `test_log_loss` / `test_brier` beat benchmark on most folds):

```bash
python Pipeline.py \
  --input_panel_csv panel_ohlcv_clean.csv \
  --output_dir pipeline_outputs_optuna \
  --enable_optuna_tuning
```

**Other options**

- `--output_dir` — directory for all outputs (required); log at `{output_dir}/00_logs/pipeline.log`
- `--no_physics_block` — exclude physics/regime features
- `--starting_capital`, `--risk_per_trade` — simulation parameters
- `--resume` — resume from last completed outer fold (same input/output_dir)

**Note:** The pipeline writes `pipeline.log` itself to `{output_dir}/00_logs/pipeline.log`. Do not redirect stdout to that file, or progress output from libraries can corrupt the log with whitespace.

## Outputs (numbered tree under `output_dir`)

The pipeline writes to numbered subdirectories. `00_logs/pipeline.log` is the run log.

| Dir | File | Description |
|-----|------|-------------|
| `00_logs/` | `pipeline.log` | Run log (authoritative) |
| `00_logs/` | `panel_timestamp_regularity_summary.json` | Per-ticker vs global timestamp coverage summary |
| `00_logs/` | `panel_timestamp_regularity_by_ticker.csv` | Per-ticker coverage (for embargo/split diagnostics) |
| `01_data/` | `model_ready_dataset.csv` | Labeled panel after feature and label construction |
| `02_metrics/` | `fold_metrics.csv` | Per-fold, per-concurrency metrics and diagnostics |
| `02_metrics/` | `trade_blotter.csv` | All simulated trades |
| `02_metrics/` | `equity_curves.csv` | Per-fold, per-concurrency equity series |
| `02_metrics/` | `selected_thresholds.csv` | Chosen (p_min, theta_ev, theta_rel) per fold and concurrency |
| `02_metrics/` | `concurrency_comparison.csv` | Aggregates by max_concurrent |
| `02_metrics/` | `threshold_candidate_diagnostics.csv` | One row per fold and threshold tuple with WRC metadata |
| `02_metrics/` | `policy_daily_returns.csv` | Stitched calendar-day strategy return series with skipped folds retained as zero-return windows |
| `02_metrics/` | `overall_metrics.json` | OOS metrics for best concurrency |
| `03_features/` | `feature_registry.csv` | Feature registry and coverage |
| `03_features/` | `feature_importances_by_fold.csv` | Base-model feature importance by fold |
| `03_features/` | `feature_stability_summary.csv` | Cross-fold importance summary |
| `04_strategies/` | `best_strategy_summary.json` | Best strategy summary |
| `05_reports/` | `equity_curve_best_concurrency.png` | Chart of chained OOS equity for best concurrency |
| `05_reports/` | `final_report.md` | Markdown summary report |
| `06_state/` | `resume_state.json` | Checkpoint for resume |
| `06_state/` | `config_snapshot.json` | Pipeline config used |
| `06_state/` | `verification.json` | Input panel checks |

## License

Use and modify as needed for research.
