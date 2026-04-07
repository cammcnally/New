# Canonical Installation Directive

## Purpose

This document is the scoped canonical authority for installation, environment,
dependency-policy interpretation, file-structure guidance, runtime-path
guidance, data-layer implementation policy, and the target daily
cross-sectional equities architecture.

It is intentionally narrower than repository governance and intentionally
narrower than the frozen downstream Phase 1 research boundary.

## Scope

This directive is canonical only for:

- installation workflow
- environment bootstrap expectations
- dependency-policy interpretation within the current repo contract
- file-structure guidance
- runtime-path guidance
- data-layer implementation policy
- target daily cross-sectional equity architecture guidance

## Non-supersession Boundary

This directive is scoped canon only. It does not supersede the higher-priority
authorities that already govern this repository.

Higher-priority surfaces that continue to win on conflict:

- `AGENTS.md`
- `docs/phase1-research-spec.md`
- `docs/phase1-execution-roadmap.md`
- `Pipeline.py`

Required interpretation rules:

- `AGENTS.md` remains the canonical policy and protected-infrastructure source
  of truth.
- The frozen Phase 1 docs remain authoritative for downstream research
  semantics and claim boundaries.
- `Pipeline.py` remains the implemented downstream compatibility runtime until a
  separate approved replacement actually lands.
- This directive may clarify scope, sequencing, and target-state architecture,
  but it may not silently broaden or rewrite the higher-priority surfaces above.

## Effective Current Canon

The effective current canon must reflect what is active today rather than what
may be desirable later.

- `uv` and `uv.lock` remain authoritative for the active environment and
  dependency workflow while `AGENTS.md` preserves them.
- `uv sync --group dev --group control-plane --group ingestion --group ingestion-test`
  remains the canonical sync command while `AGENTS.md` says so.
- Python `3.11.9` and the repo-local `.venv` remain the required local runtime
  contract.
- The implemented runtime layout remains `market_data/` plus top-level
  `Pipeline.py`.
- `configs/` remains the live market-data configuration surface.
- `config/canonical/` is a machine-readable mirror of scoped canon. It is not
  the live runtime configuration source.
- `market_data/` remains the canonical implemented data-layer root.

## Deferred Targets

The scoped canon may describe target-state architecture, but target-state
guidance must be marked as deferred until the higher-priority runtime is
actually replaced.

- Poetry is deferred and not authoritative in the current repository state.
- A `pipeline/`-first modular layout is deferred and is not the current
  implemented runtime layout.
- The target daily cross-sectional equity alpha stack is scoped target-state
  canon only. It does not automatically replace the current `Pipeline.py`
  runtime.

## Lower-Precedence Documents And Shims

The following surfaces must defer to this directive inside its scope and must
not present competing installation, layout, or runtime canon:

- `README.md`
- `docs/implementation_runbook.md`
- `market_data/COMMANDS.md`
- `docs/end_to_end_trading_system_architecture.md`

Generated compatibility shims must continue to defer upward to `AGENTS.md` and
must not treat this directive as a bootstrap or policy replacement.

## Machine-Readable Mirrors

The scoped canon is mirrored in:

- `config/canonical/runtime.yaml`
- `config/canonical/dependencies.yaml`
- `config/canonical/data.yaml`
- `config/canonical/features.yaml`
- `config/canonical/models.yaml`
- `config/canonical/validation.yaml`
- `config/canonical/portfolio.yaml`
- `config/canonical/monitoring.yaml`
- `config/canonical/reports.yaml`

Those mirrors must encode the effective current canon or explicitly mark items
as deferred. They must never pretend that a conflict with higher-priority
authority has already been resolved.

## Related Governance

Use these surfaces together:

- `docs/specs/CANONICAL_DAILY_CROSS_SECTIONAL_EQUITY_ALPHA_SPEC.md`
- `docs/governance/CHANGE_CONTROL.md`
- `docs/governance/ACCEPTANCE_GATES.md`
- `tools/verify_scoped_canon.py`

## Change Rule

If a proposed change would alter:

- protected-infrastructure authority
- frozen Phase 1 semantics
- current `Pipeline.py` compatibility behavior

then update the higher-priority governing surface first and treat this document
as downstream of that decision.
