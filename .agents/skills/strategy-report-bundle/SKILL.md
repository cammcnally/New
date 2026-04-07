---
name: strategy-report-bundle
description: Use when a task changes model outputs, backtest results, benchmark evaluation, or run artifacts and the repository must emit a polished strategy report bundle.
---

# Strategy Report Bundle

## Purpose

Ensure every important strategy run produces a reviewable, reproducible output bundle rather than raw code and scattered charts.

## Use this skill when

- a model is trained or re-evaluated
- a backtest changes
- benchmark logic changes
- report templates are edited
- diagnostics are added
- new charts or metrics are introduced

## Required bundle contents

At minimum produce:

- summary metrics
- detailed metrics
- benchmark-aware equity curve data
- trade log
- validation/fold results
- model metadata
- report manifest
- exported charts
- polished report surface

## Required report sections

1. identity / metadata
2. executive verdict
3. performance overview
4. robustness / validation
5. benchmark and risk-relative analysis
6. model diagnostics
7. trade behaviour
8. regime analysis
9. failure analysis
10. reproducibility / implementation notes
11. final decision
12. appendix

## Required mindset

A report is not a victory lap.
It is a decision artifact.

The report must help a reviewer answer:

- what was tested
- what was learned
- what failed
- what remains uncertain
- whether the strategy deserves more capital, more research, or rejection
