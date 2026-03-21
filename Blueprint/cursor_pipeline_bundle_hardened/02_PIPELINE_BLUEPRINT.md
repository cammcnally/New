# Institutional Pipeline Blueprint

> **This master file supersedes both prior versions. On conflict, Section A governs.**

## 1. Scope

This blueprint defines a **single-file, walk-forward, event-labeled, feature-discovery trading pipeline** centered on `Pipeline.py` for:

- 1-hour bar data
- long-only pooled modeling
- intended holding horizon of roughly **2 trading days to 3 trading weeks**
- broad candidate feature discovery
- strategy-library construction
- compact overwrite-oriented outputs

## 2. Data and timing conventions

### 2.1 Timeframe
- Primary timeframe: **1-hour bars**
- Session assumption: use the repo’s actual panel convention; if regular-session-only US equities, treat roughly 6.5 trading hours/day as the economic reference, but derive bars directly from the panel index rather than hard-coding session count everywhere.

### 2.2 Horizon-aware lookback ladder
Primary windows:
- 3, 5, 8
- 13, 21, 34, 55
- 89

Interpretation:
- 13 bars ≈ ~2 trading days
- 34 bars ≈ ~1 trading week
- 55 bars ≈ ~1.5–2 weeks
- 89 bars ≈ ~2.5–3 weeks

Design rule:
- use <=89 bars for primary signal features
- allow longer windows only for regime/context features and explicitly label them as such

### 2.3 Return conventions
Unless explicitly specified otherwise:
- simple return over n bars: `close_t / close_{t-n} - 1`
- log return over 1 bar: `ln(close_t / close_{t-1})`
- rolling volatility: standard deviation of 1-bar log returns over the lookback window

## 3. Predictive and policy layers

### 3.1 Predictive layer
The predictive layer estimates the probability that a clean standardized trade event succeeds.

Default target geometry unless stronger validated repo logic already exists:
- entry: next open
- stop: `entry - 1.25 * ATR_14`
- target: `entry + 2.50 * ATR_14`
- maximum horizon: 98 bars

The predictive label is not a final economic objective; it is a stable proxy feeding the policy layer.

### 3.2 Policy layer
The policy layer converts the score into decisions:
- `p_min`
- EV ranking
- concurrency allocation
- replacement logic
- final portfolio construction

This layer is evaluated on portfolio metrics, not merely on classification metrics.

## 4. Chronology and leakage rules

### 4.1 Outer split
- expanding walk-forward
- outer train window followed by outer test window
- outer-boundary purge required:
  - remove any training row whose `event_end_time >= test_start`

### 4.2 Threshold holdout
Inside purged outer-train:
- reserve a chronologically later threshold holdout
- score it out-of-sample
- choose thresholds on this scored holdout only

Default:
- `threshold_holdout_months = 3`

Threshold holdout validity:
- minimum 50 rows
- both classes present
- skip fold if invalid

### 4.3 Calibration holdout
Inside outer-train:
- reserve a chronologically later calibration holdout relative to meta-model fitting
- do not fit calibrator on rows used to fit the meta model

Default:
- `calibration_holdout_months = 2`

Calibration holdout validity:
- minimum 200 rows
- minimum 25 positives
- minimum 25 negatives
- skip fold if invalid

Calibration method:
- default: sigmoid / logistic
- isotonic only if:
  - >= 500 rows
  - >= 75 positives
  - >= 75 negatives

### 4.4 Train-only transforms
The following must be fit on training data only inside the relevant fold stage:
- orthogonality pruning
- correlation clustering
- family ranking
- feature ablation ranking
- subset search
- any learned normalization beyond simple point-in-time cross-sectional transforms
- any transform using labels

Global transforms are allowed only if they are:
- truly unsupervised
- demonstrably safe
- explicitly documented as such

## 5. Modeling stack

Required stack:
- Random Forest
- Extra Trees
- XGBoost
- LightGBM
- Elastic Net logistic baseline
- Logistic meta model
- Calibration layer

Recommended role split:
- trees for nonlinear structure
- elastic net for sparse linear benchmark and sanity check
- logistic meta for stacked combination
- calibrated final probabilities for policy decisions

## 6. Feature discovery

### 6.1 Required stages
1. all-features baseline
2. raw model importance
3. permutation importance on OOS-scored data
4. fold-stability ranking
5. family-level contribution
6. family ablation
7. regime-specific importance
8. orthogonality / redundancy pruning
9. restricted subset search on survivors
10. ranked strategy library

### 6.2 Restricted subset search
Do not brute-force the raw feature library.

Restricted subset search rules:
- operate only on survivors after pruning
- enforce family caps
- enforce orthogonality rules
- use early stopping if no candidate improves the composite strategy score
- keep candidate subset cardinalities modest:
  - e.g. 8, 12, 16, 20 maximum for strategy candidates
- stop exploring candidates that fail hard gates early

### 6.3 Promotion rules
Promote a feature only if it is:
- stable across folds (>=70% preferred)
- not a redundant copy inside a tight correlation cluster
- supported by ablation or incremental-lift evidence
- helpful downstream at the strategy level

Reject if:
- stability <50% and no exceptional incremental lift
- redundant and dominated by a stronger cluster representative
- no downstream portfolio utility

## 7. Orthogonality / family controls

### 7.1 Correlation threshold
Default near-duplicate threshold:
- 0.80 absolute correlation

### 7.2 Family cap
No single family should exceed:
- 30% of final selected features

### 7.3 Family-specific expectations
- moving averages / trend: dense family, prune aggressively
- oscillators: dense family, prefer strongest stable representative
- volatility / channels: avoid multiple near-duplicate range state measures
- volume / flow: allow complementary flow/activity measures, not many substitutes
- volatility_clustering: treat as context family, do not let it dominate
- physics/fractal: allow only stable, non-fragile members

## 8. Volatility clustering

Add a dedicated `volatility_clustering` family.

Purpose:
- model when otherwise attractive technical signals are more or less trustworthy

Required outputs:
- family importance
- family ablation
- survivor count
- contribution to final strategies

Do not hard-code regime blocks at first.  
Use regime features as context variables before considering regime-specific models or thresholds.

## 9. Information Coefficient

Primary ranking-quality metric:
- Spearman rank IC

Compute against:
1. realized R-multiple
2. forward return over horizon

Recommended operational definition:
- at each timestamp with enough candidates (prefer >=5), compute cross-sectional Spearman(score, outcome)
- fold IC = mean of timestamp-level ICs
- IC hit rate = share of positive timestamp-level ICs
- ICIR = mean IC / std(IC)

Secondary:
- pooled IC across fold
- Pearson IC as optional diagnostic

## 10. Seed robustness

### 10.1 Purpose
Avoid accepting strategies that look good only under a lucky seed.

### 10.2 Run modes
- development mode: 1 seed
- research mode: 5 seeds
- final shortlist mode: 10 seeds

### 10.3 Application
Do not sweep every seed through every stage.
Use:
- primary seed for broad discovery
- seed sweeps on shortlisted feature sets / strategies only

### 10.4 Required outputs
For shortlisted candidates:
- mean/std PF
- mean/std Calmar
- mean/std expectancy_r
- mean/std CAGR
- mean/std MDD
- mean/std log loss / Brier if relevant
- feature overlap or strategy-rank stability if feasible

## 11. Strategy library

### 11.1 Hard gates
- PF >= 1.75
- Calmar >= 1.0
- MDD <= 20%
- Expectancy_r >= 0.25
- Trades >= 200
- Positive-fold ratio >= 60%
- Top-ticker concentration <= 25%
- Churn <= 15%

### 11.2 Ranking
Primary ordering:
1. Calmar
2. PF
3. Expectancy_r
4. CAGR
5. MDD
6. Trade Count
7. ICIR

### 11.3 Tie-breakers
Use the same order, then lower concentration, then lower churn.

## 12. Output policy

Use the numbered output structure in `04_OUTPUT_FILE_POLICY.md`.

Default behavior:
- overwrite current-state artifacts
- preserve checkpoint/state artifacts needed for resume
- archive only behind explicit user flag

## 13. Human-readable final report

The final report must include:
- feature list in plain English
- family grouping
- settings / lookbacks
- exact survivor / rejection rationale
- explanation of volatility clustering and IC
- strategy-library summary
- explanation of entry, exit, ranking, and risk logic
- clear note that ensemble trees are not automatically human-readable rule systems unless a separate distillation layer is added

---

## Section B — Legacy clarifications & context

### Research questions the pipeline must answer
1. Which features matter?
2. Which feature families matter?
3. Which features are stable across folds and regimes?
4. Which features add independent lift rather than redundant noise?
5. Which constrained feature mixes translate into attractive portfolio outcomes?
6. Which strategy candidates survive the hard gates?

### Label design rationale
Binary event labels with ATR-style geometry are preferred because they provide: cleaner supervision, easier chronology control, and more stable behavior than direct continuous R-multiple regression. Continuous-return or R-multiple targets can be added later as comparison targets but should not replace the core event target until the discovery pipeline is stable.

### Validation design (must include)
- expanding outer walk-forward folds
- event-aware outer-boundary purge
- purged and embargoed inner CV
- threshold selection on a scored threshold holdout inside outer-train
- calibration on a chronologically later calibration holdout relative to meta training
- no silent neutral-probability fallback for invalid folds

### Best-practice weighting for discovery
Treat feature discovery as a combination of: tree-based importance, model-agnostic importance, linear baseline signal, and stability and ablation evidence. Do not reduce final selection to any one metric.

### Orthogonality rationale
Large indicator sets often contain many near-duplicates. A professional pipeline must avoid overcounting the same economic idea. Required mechanisms: family tagging, within-family clustering, pairwise correlation matrix, redundancy pruning threshold, incremental-lift test, family-contribution cap.

### Regime analysis
Use simple robust regimes first: high-vol / low-vol, trending / non-trending, bullish / bearish benchmark state. Feature importance and strategy performance should be reported by regime where feasible.
