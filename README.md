# Swing Trading Research Pipeline

Repository: [https://github.com/cammcnally/new](https://github.com/cammcnally/new)

A walk-forward, purged/embargoed, probability-calibrated swing-trading research pipeline. It trains stacked classifiers (RF, ET, XGB) with optional Optuna hyperparameter tuning, selects entry thresholds via in-train portfolio simulation, and evaluates out-of-sample with a 2-positions-per-ticker book simulator.

## Features

- **Panel input**: OHLCV + session flags; supports multiple tickers and timestamps
- **Feature engineering**: Returns, RSI, MACD, ATR, Bollinger, volume, cross-sectional z-scores, optional physics/regime block
- **Labels**: Long win/loss over a fixed horizon with ATR-based stop/target
- **Walk-forward**: Configurable outer train/test windows and purged inner CV for stacking
- **Stacking**: Out-of-fold base predictions → logistic meta → Platt-scaled probabilities (`p_cal`)
- **Threshold search**: Grid over `p_min`, `theta_ev`, `theta_rel`; selection by `research_score()` (Calmar, profit factor, expectancy, stability, churn)
- **Portfolio simulator**: Max concurrent positions, 2 positions per ticker, EV-in-R ranking, replacement exits, time exits aligned to label geometry
- **Optuna** (optional): Tune RF/ET/XGB on mean inner-fold log loss; tuned params used in both OOF and full-train base models when enabled
- **Baseline gating**: Benchmark base-rate metrics; enable tuning only after baseline beats benchmark on a majority of folds
- **Outputs**: Fold metrics, trade blotter, equity curves, chained OOS equity, selected thresholds CSV, feature importance, markdown report, JSON config/metrics

## Requirements

- Python 3.8+
- See `requirements.txt` (pandas, numpy, matplotlib, scikit-learn, xgboost, tabulate, optuna)

```bash
pip install -r requirements.txt
```

## Input

- **Panel CSV**: `panel_ohlcv_clean.csv` (or path via `--input_panel_csv`) with columns: `ticker`, `timestamp_utc`, `open`, `high`, `low`, `close`, `volume`, `is_incomplete_session`.

## Usage

**Baseline (no tuning)** — run first and confirm fold metrics and benchmark pass:

```bash
python full_pipeline_beginning_to_end.py \
  --input_panel_csv panel_ohlcv_clean.csv \
  --output_dir pipeline_outputs
```

**With Optuna tuning** — only after baseline looks good (e.g. `test_log_loss` / `test_brier` beat benchmark on most folds):

```bash
python full_pipeline_beginning_to_end.py \
  --input_panel_csv panel_ohlcv_clean.csv \
  --output_dir pipeline_outputs_optuna \
  --enable_optuna_tuning
```

**Other options**

- `--output_dir` — directory for all outputs (required)
- `--no_physics_block` — exclude physics/regime features
- `--starting_capital`, `--risk_per_trade` — simulation parameters
- `--resume` — resume from last completed outer fold (same input/output_dir)
- `--max_folds` — run only the first N outer folds (e.g. for smoke tests)

## Outputs (in `output_dir`)

| File | Description |
|------|-------------|
| `pipeline.log` | Run log |
| `model_ready_dataset.csv` | Labeled panel after feature and label construction |
| `fold_metrics.csv` | Per-fold, per-concurrency metrics and diagnostics |
| `trade_blotter.csv` | All simulated trades |
| `equity_curves.csv` | Per-fold, per-concurrency equity series |
| `selected_thresholds.csv` | Chosen (p_min, theta_ev, theta_rel) per fold and concurrency |
| `concurrency_comparison.csv` | Aggregates by max_concurrent |
| `feature_importances_by_fold.csv` | Base-model feature importance by fold |
| `feature_stability_summary.csv` | Cross-fold importance summary |
| `equity_curve_best_concurrency.png` | Chart of chained OOS equity for best concurrency |
| `verification.json` | Input panel checks |
| `config.json` | Pipeline config used |
| `overall_metrics.json` | OOS metrics for best concurrency |
| `final_report.md` | Markdown summary report |

## License

Use and modify as needed for research.
