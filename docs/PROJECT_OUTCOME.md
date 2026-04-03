# Project Outcome

Build a production-grade Python machine-learning trading pipeline that is:

- point-in-time correct
- benchmark-aware
- reproducible
- strategy-reporting capable
- robust against overfitting
- honest about uncertainty
- executable as a research system, not just a notebook collection

## Core outcome

The repository must support the full chain:

1. define a research question and tradable target
2. acquire and validate data
3. build features without lookahead
4. train models with deterministic configs and seeds
5. evaluate signals and strategies out of sample
6. compare against canonical benchmarks and risk-free series
7. produce institutional-grade reports and machine-readable artifacts
8. fail clearly when assumptions or contracts are violated

The broader target-state downstream architecture that fills in this chain at the system-design level is documented in `docs/end_to_end_trading_system_architecture.md`. That document is the repo-native consolidation point for the expanded cross-sectional equity architecture, while `docs/phase1-research-spec.md` remains the frozen authority for current Phase 1 claim boundaries.

## Non-negotiable invariants

- No lookahead leakage.
- No hidden data joins.
- No silent benchmark inference.
- No notebook-only logic for core pipeline behavior.
- No “works on my machine” artifacts.
- No result is considered valid without out-of-sample evidence.
- No fix is complete without root-cause understanding.
- Every important run must emit reproducible artifacts.

## Canonical benchmark semantics

- Market benchmark: SPY
- Sector layer: 11 sector ETFs
- Risk-free source: DFF on the macro path
- Context series may exist, but they are not primary benchmark semantics

## Definition of done

A task is done only when:

- the code is integrated cleanly
- tests or validations exist at the correct layer
- contracts and docs are consistent
- artifacts/reports are updated when outputs change
- the change improves the repo toward the core outcome above
