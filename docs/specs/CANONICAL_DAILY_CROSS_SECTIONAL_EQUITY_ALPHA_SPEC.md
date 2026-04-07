# Canonical Daily Cross-Sectional Equity Alpha Spec

## Purpose

This document captures the scoped target-state architecture canon for the
repository's daily cross-sectional equity alpha stack.

It is a future-state design authority within the scope defined by
`docs/specs/CANONICAL_INSTALLATION_DIRECTIVE.md`.
It is not a claim that the current Phase 1 runtime has already been replaced.

## Status And Authority Boundary

This spec is authoritative only for deferred target-state architecture choices.
It does not supersede:

- `AGENTS.md`
- `docs/phase1-research-spec.md`
- `docs/phase1-execution-roadmap.md`
- `Pipeline.py`

Current effective implementation remains:

- canonical data layer rooted in `market_data/`
- downstream compatibility runtime rooted in top-level `Pipeline.py`
- frozen Phase 1 semantics governed by `docs/phase1-*.md`

## Decision Law

Target-state decision timing remains:

`signal_t -> trade_{t+1 open}`

## Target Architecture Summary

### Universe

- training universe: top `1000` equities by daily ADV
- trading universe: top `150` equities by daily ADV

### Labels

- `1D`
- `5D`
- `20D`

### Feature Stack

The preferred target stack includes:

- returns over multiple horizons
- rolling volatility
- momentum decay
- liquidity context
- cross-sectional rank companions
- fixed interaction terms
- train-only neutralization, scaling, and PCA
- regime context for downstream conditioning and diagnostics

### Validation

The preferred target validation geometry is:

- purged walk-forward CV
- `756D` train window
- `21D` test step
- `20D` embargo

### Model Stack

The preferred target model stack is:

- ridge regression
- XGBoost
- neural network

### Portfolio Construction

The preferred target portfolio is:

- market-neutral
- sector-neutral
- long/short
- gross exposure `1.0`
- net exposure `0.0`
- max position `2%`

### Monitoring And Retraining

The preferred target operating overlays include:

- weekly retraining
- retrain if `IC` drops by more than `30%`
- retrain if Sharpe drops by more than `20%`

### Reports

The preferred target reporting bundle includes:

- equity curve
- drawdown curve
- `IC` over time
- feature-importance outputs
- turnover diagnostics
- data, feature, model, and portfolio summaries

## Mirror Mapping

Machine-readable mirrors for this target-state canon live in:

- `config/canonical/features.yaml`
- `config/canonical/models.yaml`
- `config/canonical/validation.yaml`
- `config/canonical/portfolio.yaml`
- `config/canonical/monitoring.yaml`
- `config/canonical/reports.yaml`

Runtime and installation mirrors stay in:

- `config/canonical/runtime.yaml`
- `config/canonical/dependencies.yaml`
- `config/canonical/data.yaml`

## Non-Activation Rule

This target-state architecture does not become the active implementation until a
separate approved migration updates the higher-priority governing surfaces as
needed and lands the corresponding runtime code changes.
