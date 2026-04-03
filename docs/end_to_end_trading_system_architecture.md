# End-To-End Trading System Architecture

## Purpose

This document consolidates the three-part trading-system brief into a single repo-native target architecture for the broader downstream research and trading stack.

It keeps the most specific non-contradictory choices, resolves internal draft conflicts, and maps the result onto the repository's existing authority boundaries.

### Authority boundaries

- `docs/data_contract.md` remains authoritative for canonical market-data, point-in-time (PIT) rules, benchmark semantics, manifests, and export contracts.
- `docs/phase1-research-spec.md` and `docs/phase1-execution-roadmap.md` remain authoritative for the current frozen Phase 1 claim boundary and validation semantics.
- This document defines the broader target-state architecture for future full-system integration, post-Phase 1 planning, and cross-layer design decisions.

This document does not by itself broaden current Phase 1 claims.

## Consolidation rules

1. When the three source messages disagree, the later locked setting wins.
2. Earlier formulas, rationale, and controls are retained when they do not conflict with the later locked setting.
3. Superseded draft ideas remain discoverable in the final section, but they are non-normative.

## Repo integration map

| Layer | Repo surfaces | Role in this architecture |
| --- | --- | --- |
| Canonical data plane | `market_data/**/*`, `configs/**/*.yaml`, `docs/data_contract.md` | PIT-safe identity, prices, benchmarks, compatibility exports, dataset and export build references |
| Frozen Phase 1 runtime | `Pipeline.py`, `feature_registry/**/*`, `docs/phase1-*.md` | Current validated downstream implementation and current claim boundary |
| Broader target architecture | `docs/end_to_end_trading_system_architecture.md` | Future-state universe, features, validation, models, portfolio, execution, monitoring, and reporting design |
| Reporting and artifacts | `docs/ARTIFACT_CONTRACT.md`, `strategy-report.qmd`, `mlflow_integration/**/*` | Deterministic artifact bundle, report rendering, and experiment tracking |

## 1. System objective and locked flow

The target system is a deterministic, cross-sectional, daily U.S. equity research and trading stack that:

- trains on a broad liquid universe for statistical power
- trades a tighter liquid universe for execution efficiency
- predicts `1D`, `5D`, and `20D` forward returns
- ranks securities cross-sectionally
- constructs a sector-neutral, market-neutral long/short portfolio
- prices execution with explicit costs and ADV-aware slippage
- emits auditable artifacts and reviewable reports

Decision timing:

`signal_t -> trade_{t+1 open}`

Locked end-to-end flow:

`Top 1000 -> Feature generation -> Neutralize -> Scale -> PCA -> Regime detection -> Models (3 per horizon) -> Purged walk-forward CV -> Ensemble -> Predict -> Rank -> Select Top 150 -> Optimize -> Trade t+1 -> Evaluate -> Retrain`

## 2. Locked core configuration

### 2.1 Core locked settings

| Setting | Value |
| --- | --- |
| data_frequency | daily |
| rebalance_frequency | daily |
| training_universe | Top 1000 equities by daily ADV |
| trading_universe | Top 150 equities by daily ADV |
| prediction_horizons | `1D`, `5D`, `20D` |
| lookback_window | `252D` |
| training_window | `756D` (3 years) |
| test_step | `21D` (monthly) |
| embargo | `20D` |
| transaction_cost | `10` bps |
| slippage_model | `sqrt(size / ADV)` |
| max_trade_size | `10% ADV` |
| max_position | `2%` per asset |
| gross_exposure | `1.0` |
| net_exposure | `0.0` |
| sector_neutral | `true` |
| retraining_frequency | weekly |
| retraining_triggers | `IC_drop > 30%`, `Sharpe_drop > 20%` |
| storage_format | parquet |
| storage_dtype | `float32` |
| storage_partition | `date`, `ticker` |
| deterministic_seeds | `numpy=42`, `torch=42` |

### 2.2 Earlier controls preserved as operating overlays

The earlier drafts also carried non-conflicting controls that should remain part of the operating design:

- target annualized portfolio volatility: `10%`
- daily turnover should be penalized in optimization and monitored against a `30%` warning threshold
- max drawdown should be monitored against a `20%` operating guardrail, while the wider integrity screen remains `25%`
- modeled costs must be included in every evaluation

## 3. Universe, data, and timeline discipline

### 3.1 Dual-universe policy

The final universe definition resolves the earlier single `150`-name wording into a dual-universe design:

- **Training universe:** top `1000` equities by daily ADV, time-varying
- **Trading universe:** top `150` equities by daily ADV, time-varying

Rule:

`Universe_train_t superset Universe_trade_t`

Purpose:

- training needs breadth and statistical power
- trading needs tighter liquidity and execution realism

Average daily dollar volume:

`ADV_i = (1 / N) * sum_{t=1..N}(Price_{i,t} * Volume_{i,t})`

Concrete market-data eligibility filters such as security type, listing age, minimum price, and other canonical universe screens remain owned by `configs/universe.yaml` and the canonical market-data layer. This document defines the downstream daily selection policy on top of that canonical eligibility set.

### 3.2 Single timeline index

All data is aligned to one trading-date index `t`.

Core law:

`X_t -> y_{t+h}`

Implications:

- every feature must be computed from information available by the decision time at `t`
- every label must correspond to a tradable future outcome after `t`
- benchmark, macro, and classification joins must obey the PIT rules defined in `docs/data_contract.md`
- execution assumptions must stay aligned to `signal_t -> trade_{t+1 open}`

### 3.3 PIT normalization and corporate actions

The earlier brief required corporate-action-aware normalization. In repo terms, that consolidates into the following rule:

- canonical storage remains explicit and contract-safe at the market-data layer
- any adjusted or total-return surface must be a named derived artifact, never a silent mutation of the canonical unadjusted OHLCV contract

Illustrative adjusted-price form:

`P_adj_t = P_t * product(1 - split_or_dividend_adjustment)`

This is a downstream analytical transform, not a license to rewrite canonical market-data contracts in place.

### 3.4 Fit-versus-transform separation

The broader spec and the repo's current validation rules are aligned on the same fit/transform law:

| Component | Fit on | Apply to |
| --- | --- | --- |
| neutralization and scaling | train only | train and test |
| PCA | train only | train and test |
| predictive models | train only | test |
| fold-local ranking or calibration maps | fold-local train or calibration data only | matching fold test only |

No transformation may be fit on future rows and then back-applied historically.

## 4. Labels and feature stack

### 4.1 Non-overlapping labels

The final locked target is horizon-specific forward return prediction with non-overlapping labels for the longer horizons.

`1D: y_t^(1D) = (P_{t+1} / P_t) - 1`

`5D: y_t^(5D) = (P_{t+5} / P_t) - 1`, sampled every 5th observation only

`20D: y_t^(20D) = (P_{t+20} / P_t) - 1`, sampled every 20th observation only

This preserves the earlier insistence on honest label geometry while removing overlapping-horizon leakage from the locked configuration.

### 4.2 Exact per-asset feature families

Per asset per day, the locked feature stack is:

1. **Returns**
   - `1D`, `5D`, `20D`, `60D`
2. **Volatility**
   - rolling standard deviation over `10D`, `20D`, `60D`
3. **Momentum decay**
   - exponential decay with `lambda = 0.1`
   - window = `60`
4. **Liquidity**
   - `log(ADV)`
   - `delta ADV`
5. **Cross-sectional rank companions**
   - daily cross-sectional rank of the feature values
6. **Fixed interaction terms**
   - `momentum x volatility`
   - `return x rank`
   - `volatility x liquidity`

All features are strictly lagged to preserve the decision law:

`X_t predicts y_{t+h}`

### 4.3 Cleaning, scaling, and neutralization

The locked feature-processing path is:

1. winsorize at `+/- 3 sigma`
2. daily cross-sectional z-score normalization
3. mandatory market and sector neutralization

Neutralization form:

`X_neutral = X - beta_m * M - sum(beta_s * S_s)`

Where:

- `M` is the market return factor
- `S_s` are sector dummies

This keeps the earlier cross-sectional normalization requirement while binding it to an explicit neutralization step.

### 4.4 Feature selection and dimensionality reduction

The broader draft included both pruning and compression. The consolidated target keeps:

- IC filter: retain features with `|IC| > 0.02`
- correlation pruning: remove pairs where `corr(X_i, X_j) > 0.9`
- PCA fit on training data only
- retain `95%` explained variance
- typical PCA output: `20` to `40` components

There is no alternative dimensionality-reduction path in the locked configuration.

### 4.5 Regime context

The fixed regime model is a `2`-state Hidden Markov Model:

Inputs:

- market return via `SPY` proxy
- `VIX` proxy or realized volatility

States:

- low volatility
- high volatility

Regime context feeds model conditioning, ensemble behavior, and diagnostics. Benchmark semantics remain governed by `docs/data_contract.md`.

## 5. Validation, loss, and model stack

### 5.1 Validation geometry

The locked validation method is purged walk-forward cross-validation:

- folds: `5`
- train window: `756D`
- test window: `21D`
- embargo: `20D`

Additional integrity rules preserved from the earlier drafts:

- do not use standard shuffled K-fold for time series
- preserve a final untouched hold-out slice for true out-of-sample confirmation when model-selection risk is material
- hyperparameter selection must use only training and CV data, never the untouched hold-out

### 5.2 Locked loss function

Primary objective:

`L = -corr(R_hat_{:,t}, R_{:,t})`

Secondary downside penalty:

`L_final = L + 2 * max(0, -R_hat)^2`

Interpretation:

- optimize cross-sectional ranking quality first
- explicitly punish downside-skewed predictions
- treat MSE, Sharpe, and Sortino as auxiliary evaluation metrics rather than the primary training objective

### 5.3 Exact model stack

Run `3` separate pipelines per horizon.

#### Ridge regression

- `alpha = 1.0`
- `fit_intercept = true`

#### XGBoost

- `max_depth = 5`
- `learning_rate = 0.05`
- `n_estimators = 300`
- `subsample = 0.8`
- `colsample_bytree = 0.8`

#### Neural network

- layers: `[64, 64]`
- activation: `ReLU`
- dropout: `0.2`
- optimizer: `Adam`
- learning_rate: `1e-3`
- epochs: `20`
- batch_size: `512`

### 5.4 Ensemble method

Step 1:

`IC_m = corr(R_hat_m, R)`

Step 2:

compute the correlation matrix across model predictions

Step 3:

`w_m = IC_m / sum(corr(m, others))`

Normalize:

`sum(w_m) = 1`

Final prediction:

`R_hat_final = sum(w_m * R_hat_m)`

Weights must be derived only from training or fold-local validation outputs, never from future hold-out data.

### 5.5 Numerical stability controls

The earlier infrastructure draft included explicit numerical guardrails that remain valid:

- use `epsilon = 1e-8` to avoid divide-by-zero in volatility and ratio terms
- clip predictions to `[-0.2, 0.2]`
- prefer `float32` where precision is sufficient

## 6. Portfolio construction, risk, and execution

### 6.1 Ranking and security selection

For each date:

1. rank the final predictions cross-sectionally
2. convert ranks to percentiles

`Score_i = rank_i / N`

Selection:

- long: top `15%`
- short: bottom `15%`

Selection happens inside the daily trading universe of the top `150` names by ADV.

### 6.2 Optimization

Locked portfolio construction:

- pre-constraint score weight: `w_i proportional to Score_i - 0.5`
- objective: mean-variance with turnover penalty

Objective:

`max_w (w^T * mu - lambda * w^T * Sigma_prime * w)`

Shrunk covariance:

`Sigma_prime = 0.8 * Sigma + 0.2 * I`

Turnover penalty:

`Penalty = eta * sum(|w_t - w_{t-1}|)`

Constraints:

- `|w_i| <= 0.02`
- gross exposure `<= 1.0`
- net exposure `= 0.0`
- sector neutrality required

### 6.3 Risk overlays

The earlier drafts added operational overlays that remain part of the consolidated design:

- target `10%` annualized portfolio volatility
- daily turnover monitoring threshold `30%`
- operating drawdown guardrail `20%`
- wider research integrity ceiling `25%`

These overlays complement the optimizer; they do not replace the locked score-to-weight and covariance-aware portfolio path.

### 6.4 Execution and capacity

Execution timing:

`signal_t -> trade_{t+1 open}`

Execution rules:

- max trade size: `10% ADV`
- slippage: proportional to `sqrt(size / ADV)`
- transaction cost: `10` bps
- execution style: `VWAP`

Capacity discipline:

- use lagged liquidity only
- never use future ADV or future market-depth information
- treat any trade or position that cannot be supported within the ADV limits as capacity-constrained

## 7. Monitoring, feedback, and failure handling

### 7.1 Weekly retraining policy

- retrain weekly
- force retrain if `IC` drops by more than `30%`
- force retrain if Sharpe drops by more than `20%`

### 7.2 Mandatory diagnostics

Track at minimum:

- information coefficient (`IC`)
- rolling or decayed `IC`
- hit ratio
- turnover
- max drawdown
- feature importance drift
- turnover spikes
- regime stability or breakdown

### 7.3 Failure modes and required actions

Detect:

- overfitting: train Sharpe materially greater than test Sharpe
- regime breakdown: `IC` flips sign or collapses by regime
- capacity stress: turnover or ADV usage exceeds expected bounds

Response:

- reduce model weight
- trigger retraining
- escalate the run as degraded instead of silently accepting it

### 7.4 Performance integrity checks

Before accepting a result:

- train Sharpe should stay within roughly `+/- 30%` of test Sharpe
- `IC` should remain directionally stable over time
- drawdown should remain below `25%`
- turnover should remain within the declared operating limits
- portfolio constraints must be enforced before execution
- costs must be included in every evaluation

## 8. Data handling, determinism, and reporting

### 8.1 Storage and compute strategy

Use:

- parquet for persisted tables
- `float32` where appropriate
- partitioning by `date` and `ticker`
- chunked loading
- lazy evaluation with engines such as Polars or Dask where scale requires it
- sparse matrices when feature density allows it
- CPU multiprocessing or GPU acceleration for model training where justified

Dependency stack expected by the source brief:

- core numerics: `numpy`, `pandas`, `scipy`
- ML: `scikit-learn`, `xgboost`, `lightgbm`, `torch`
- time-series and finance: `statsmodels`, `arch`, `ta-lib`
- data handling: `pyarrow`, `polars`, `dask`
- optimization and experiment tracking: `cvxpy`, `mlflow`
- reporting and interpretation: `matplotlib`, `seaborn`, `plotly`, `shap`

Any future dependency changes still need to follow the repo's dependency policy and authoritative manifests.

### 8.2 Auditability and determinism

Compliant runs should carry:

- immutable raw and processed data references
- dataset and export build references from the canonical market-data layer
- deterministic seeds
- full logging for feature generation, model training, predictions, and trades
- experiment tracking through MLflow or an equivalent registry

Track at minimum:

- parameters
- features used
- model versions
- metrics
- dataset and export build references

### 8.3 Reporting surfaces

The original brief emphasized a Jupyter reporting layer. In this repo, that intent consolidates into an artifact-first reporting rule:

- exploratory notebooks are acceptable for inspection
- notebook-only delivery is not sufficient for repo-grade research output
- durable outputs must land in canonical artifacts and report surfaces

Required analytical outputs:

- equity curve
- drawdown curve
- `IC` over time
- feature importance, including SHAP where applicable
- turnover
- data validation summary
- feature validation summary
- model diagnostics
- portfolio diagnostics

Preferred tooling:

- `matplotlib`
- `seaborn`
- `plotly`
- `shap`

### 8.4 Preferred module seams

The earlier architecture draft proposed a modular code layout:

```text
pipeline/
  data/
  features/
  models/
  optimization/
  backtest/
  reports/
```

That structure is the preferred target decomposition for broader future work. It is not a requirement to refactor `Pipeline.py` before Phase 1 completion. Until the Phase 1 boundary is crossed, use this layout as an extraction target rather than as an excuse for premature structural churn.

## 9. Non-negotiable design laws

The three source messages aligned on the following non-negotiables:

- all features are strictly lagged
- cross-sectional normalization is performed daily
- models are retrained on rolling or walk-forward windows only
- scaling, neutralization, and PCA are fit on training data only
- portfolio constraints are enforced before execution
- costs are included in every meaningful evaluation
- outputs are auditable and reproducible
- no forward-looking bias or hidden joins are allowed

## 10. Ordered implementation sequence

The source brief included a calendar-week build plan. To stay consistent with repo planning rules, it is consolidated here as an ordered implementation sequence rather than a date estimate:

1. canonical data ingestion, cleaning, and universe definition
2. feature engine, leakage controls, and validation diagnostics
3. model stack, purged walk-forward CV, and ensemble logic
4. portfolio optimization, execution modeling, and backtesting
5. reporting, experiment tracking, and auditability hardening

## 11. Target properties of a compliant implementation

If implemented in a repo-consistent way, this architecture should be:

- auditable: every output traceable to data, config, and model lineage
- reproducible: deterministic reruns under fixed data and seeds
- statistically valid: no leakage, honest CV, untouched final validation
- operationally feasible: liquidity-aware universes, ADV-aware execution, bounded exposures
- interpretable: diagnostics and reports explain both wins and failures

## 12. Superseded draft elements

The earlier messages included ideas that were useful during exploration but are not part of the locked core configuration:

- anomaly-detection layers such as z-score anomaly flags or Isolation Forest
- autoencoder-based dimensionality reduction
- binary classification targets, weighted loss, or focal-loss branches
- MSE-, Sharpe-, or Sortino-first training objectives
- top and bottom `20%` bucket selection
- a single `150`-name universe for both training and trading
- calendar-week implementation estimates

These remain draft-only unless they are reintroduced through an explicit doc-first update.
