# Implementation Runbook

## Purpose

This is the authoritative local runbook for the canonical market-data layer and the downstream `Pipeline.py` compatibility run.

The repo has two explicit layers:

1. `market_data` is the canonical market-data platform and source of truth.
2. `Pipeline.py` is the downstream Phase 1 research pipeline that consumes a derived/exported compatibility surface.

Use this runbook when running the repo end to end, resuming after failure, or triaging scoped verification issues.

## Authoritative Local Commands

Primary entrypoints:

```powershell
make e2e
uv run python tools/run_repo_e2e.py
```

For a maintained list of common end-to-end failures by stage (symptoms, causes, mitigations), see [e2e-run-blockers.md](e2e-run-blockers.md).

For a **file-only** overnight repair contract (no hooks), see [ops/overnight/README.md](../ops/overnight/README.md), [ops/overnight/e2e_definition.md](../ops/overnight/e2e_definition.md), and [ops/overnight/e2e_contract.json](../ops/overnight/e2e_contract.json).

Verification entrypoints:

```powershell
uv run python tools/verify_market_data_contracts.py
uv run python tools/verify_market_data_docs_sync.py
uv run python tools/verify_market_data_pit.py
uv run python tools/verify_market_data_bridge.py
uv run python tools/verify_market_data.py
```

## Stage Order

The authoritative e2e flow runs these stages in order:

1. dependency sync
2. canonical market-data ingest/build
3. market-data verification guards
4. compatibility export
5. downstream `Pipeline.py` run
6. report, manifest, and status rendering

Required guard names:

- `schema_guard`
- `docs_sync_guard`
- `pit_guard`
- `compat_guard`
- `bridge_guard`
- `verification_guard`

## Expected Outputs

An e2e run is expected to leave these outputs on disk:

- canonicalized `market_data` artifacts in the data lake
- exported `panel_ohlcv_clean.csv`
- export manifest/sidecar with `export_panel_version_id`
- dataset manifest with `dataset_build_id`
- verification JSON and Markdown summaries
- downstream pipeline outputs under the configured output directory
- a final status summary aligned with `docs/run_status.md`

## Resume And Scoped Reruns

Preferred rerun commands:

```powershell
uv run python tools/run_repo_e2e.py --resume
uv run python tools/run_repo_e2e.py --from-stage verify_market_data
uv run python tools/run_repo_e2e.py --stop-after export_panel
```

Use `--resume` when:

- the prior run wrote an e2e state/status artifact
- the same effective configuration and output locations still apply

Use `--from-stage` when:

- a localized fix invalidated one or more downstream stages
- you want to rerun only the earliest affected stage and everything after it

Use `--stop-after` when:

- you are validating a bounded change such as contracts, bridge behavior, or manifest generation

## Failure Handling Rules

The e2e flow is fail-closed.

When a step fails:

1. inspect the failing stage and its log reference
2. diagnose the actual cause
3. patch the smallest correct surface
4. rerun the affected verifier or test first
5. rerun the earliest invalidated e2e stage
6. continue automatically only after the fix is verified

Stop only when a true hard blocker remains.

## Hard Blocker Standard

A hard blocker is one of:

- missing required credentials or environment prerequisites
- upstream source outage or data unavailability that cannot be worked around safely
- contract or PIT ambiguity that cannot be resolved without changing normative governance
- protected-infrastructure approval boundary that has not been satisfied

When blocked, write a concise blocker report containing:

- failing stage
- failing command
- observed error
- why it is not safely auto-fixable
- what remains implementable
- exact next action for the operator

## Verification Expectations

Do not treat compile success or a partial run as completion.

Before closing work:

- market-data contract tests must pass
- PIT leakage checks must pass
- bridge/export compatibility checks must pass
- docs-sync checks must pass
- the authoritative e2e command must complete
- manifests and status outputs must be written

## Reporting Discipline

Every substantial change report should include:

1. files changed
2. commands added or updated
3. tests and verification run
4. manifest/build-ID impact
5. compatibility impact
6. outputs written
7. deferred items still remaining
8. de-prioritized items parked for later revisit
