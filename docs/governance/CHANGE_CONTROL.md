# Deferred Target-State Spec Change Control

## Purpose

This document defines how deferred target-state spec changes must move through the repository without silently overriding higher-priority authority.

It governs the deferred spec surfaces under `docs/specs/`, the companion governance notes in `docs/governance/`, and the mirror files under `config/canonical/`.
Repo-wide authority enforcement lives in `docs/governance/REPO_AUTHORITY_POLICY.md`, `config/canonical/repo_authority.yaml`, and the `repo-governance` CI lane.

## Precedence Order

Use this order whenever deferred target-state spec surfaces and existing repo governance meet:

1. `AGENTS.md`
2. `docs/phase1-research-spec.md`
3. `docs/phase1-execution-roadmap.md`
4. current implemented `Pipeline.py` behavior
5. `docs/specs/CANONICAL_INSTALLATION_DIRECTIVE.md`
6. `docs/specs/CANONICAL_DAILY_CROSS_SECTIONAL_EQUITY_ALPHA_SPEC.md`
7. `config/canonical/*.yaml`
8. `README.md`, `docs/implementation_runbook.md`, `market_data/COMMANDS.md`,
   and `docs/end_to_end_trading_system_architecture.md`

## Required Update Sets

### In-Scope Deferred-Spec Change

If the change stays within the deferred target-state spec surfaces and does not alter
higher-priority meaning, update all affected surfaces together:

- the relevant doc under `docs/specs/`
- the matching file or files under `config/canonical/`
- the lower-precedence docs that summarize the deferred target-state specs
- `tools/verify_scoped_canon.py`
- targeted tests that enforce the contract

### Higher-Priority Change

If the change would alter:

- protected infrastructure or bootstrap authority
- frozen Phase 1 semantics
- current `Pipeline.py` compatibility behavior

then update the higher-priority governing surface first. Do not try to smuggle
that change through deferred-spec docs or mirrors.

## Prohibited Shortcuts

Do not:

- claim Poetry is already authoritative while `AGENTS.md` still freezes `uv`
  and `uv.lock`
- claim a `pipeline/`-first layout is already the implemented runtime while
  `market_data/` plus top-level `Pipeline.py` remain active
- claim the target daily cross-sectional alpha stack already replaced the frozen
  Phase 1 runtime
- treat `config/canonical/` as the live runtime config source
- use broader architecture notes to reinterpret current Phase 1 semantics

## Required Verification

Before closing deferred target-state spec work, run:

- `uv run python tools/verify_scoped_canon.py`
- `uv run python tools/verify_frozen_surfaces.py`
- `uv run python tools/verify_tracked_locks.py`
- targeted pytest coverage for deferred-spec and control-plane precedence checks
