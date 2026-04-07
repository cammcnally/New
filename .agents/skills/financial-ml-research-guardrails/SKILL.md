---
name: financial-ml-research-guardrails
description: Use when designing features, labels, experiments, cross-validation, backtests, or alpha diagnostics for machine-learning trading research.
---

# Financial ML Research Guardrails

## Purpose

Preserve research integrity while moving fast.

## Use this skill when

- creating labels
- creating features
- creating train/test splits
- choosing benchmarks
- evaluating model outputs
- reviewing a backtest or experiment design
- deciding whether a result is strong enough to continue

## Core questions to answer first

1. What is the tradable decision being made?
2. When is the decision made?
3. What data was actually available then?
4. What is the execution assumption?
5. What is the benchmark or opportunity-cost baseline?
6. What would make this result obviously invalid?

## Required checks

### Feature integrity

- no future leakage
- no revised-data leakage unless vintage-aware
- no present-day classification or metadata injected historically
- features must align to the exact prediction horizon and execution timing

### Label integrity

- labels must reflect tradable outcomes
- the return horizon must match the intended strategy horizon
- any overlap or serial dependence should be acknowledged in validation

### Validation integrity

- require honest out-of-sample evaluation
- prefer walk-forward / purged / embargo-aware approaches where relevant
- preserve a final untouched decision set when model selection risk is high

### Overfitting discipline

Assume overfitting is the default failure mode until evidence says otherwise.
Ask:

- does the result survive costs?
- does it survive across folds?
- is it concentrated in one regime?
- does it collapse after removing the best period or top few trades?
- is it only a sector or benchmark effect?

### Benchmark discipline

- compare against the correct market benchmark
- use sector/group context where available
- use risk-free context where relevant
- never confuse a predictive signal with a complete strategy

## Recommended outputs

For signal-level work:

- bucket/quantile returns
- IC and rolling IC
- turnover / rank autocorrelation
- by-group / by-sector decomposition

For strategy-level work:

- CAGR / vol / Sharpe / Sortino
- drawdown
- active return vs benchmark
- tracking error / information ratio
- regime breakdown
- failure analysis

## Final mindset

The goal is not to prove that a strategy works.
The goal is to find out whether it still works after honest pressure is applied.
