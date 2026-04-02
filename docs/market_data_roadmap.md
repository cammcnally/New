# Market Data Roadmap

This document tracks visible follow-on work that is intentionally de-prioritized behind contract correctness, PIT safety, canonical identity, bridge integrity, manifest trustworthiness, and documentation synchronization.

## Current Priority Order

### Active Now

- Pandera contracts for canonical and bridge surfaces
- canonical identity cutover
- required-core versus optional-enrichment simplification
- generated-only compatibility surfaces
- trustworthy dataset/export manifests
- verification entrypoints and fail-closed guards
- authoritative e2e local entrypoint
- docs synchronization across `README.md`, `docs/data_contract.md`, and `market_data/COMMANDS.md`
- `Pipeline.py`, MLflow, and file-backed OpenLineage threading for `dataset_build_id` and `export_panel_version_id`

### Next Up

- stronger PIT leakage verification
- stronger symbol mapping coverage
- benchmark coverage hardening
- verification-lane consolidation so e2e and guard bundles stop duplicating work
- DuckDB and Parquet convention hardening
- file-vitality registry and cleanup audit tooling

### After That

- narrow DVC coverage for exported datasets, manifests, and verification artifacts
- additional export reproducibility checks

## Deferred Items And Revisit Conditions

### Dagster Expansion

Status: de-prioritized

Do not expand Dagster while it still mostly wraps the compatibility/export path.

Revisit when:

- canonical market-data tables and verification are stable
- the repo wants Dagster to become the authoritative asset graph for `market_data`
- the e2e path is no longer centered on the direct local runner

### Prefect

Status: de-prioritized

Do not add Prefect now.

Revisit when:

- `market_data/orchestration/sync.py` becomes operationally hard to schedule, recover, monitor, or rerun safely with the current approach

### lakeFS

Status: de-prioritized

Revisit when:

- the repo moves to S3, MinIO, Azure Blob, or another object-store-first setup
- collaborative multi-machine data workflows make object-storage-native versioning worth the complexity

### Great Expectations Expansion

Status: de-prioritized

Keep GE narrow and secondary while Pandera remains the primary contract layer.

Revisit when:

- Pandera contracts are stable
- a concrete artifact-validation gap remains that Pandera does not cover cleanly
- the repo still needs an additional artifact expectation layer after the verifier entrypoints are in place

### Broad DVC Expansion

Status: de-prioritized

Keep DVC narrow at first.

Revisit when:

- exported-build reproducibility is solved with the narrow tracked set
- broader DVC coverage would reduce real operational risk instead of adding tool sprawl

### MCP Expansion

Status: de-prioritized

Do not add MCP integrations for novelty or duplicated local-file behavior.

Revisit when:

- GitHub PR or issue workflows need direct integration
- dataset metadata catalog access becomes high value
- verification artifact access needs a safer read interface
- controlled DuckDB query access would materially improve operator workflows

### Heavy Subagent Proliferation

Status: de-prioritized

Keep the agent count small unless a repeated workflow proves specialized roles are worth the coordination cost.

Revisit when:

- rules, hooks, and skills are stable
- a repeated workflow clearly benefits from more specialized role separation

### Broader Orchestration Refactors

Status: de-prioritized

Do not begin large orchestration rewrites while the repo still needs canonical cutover, verifier hardening, and e2e stabilization.

Revisit when:

- the canonical identity path is stable
- verifier entrypoints and manifests are stable
- repeated runtime failures show that the current orchestration layout is materially slowing diagnosis or recovery

### Authoritative Historical Classification

Status: deferred

Revisit when:

- a date-effective classification source is selected
- window integrity and historical completeness can be validated
- sector-relative features or benchmark mappings need to move from disabled/deferred to active

### Full Fundamentals PIT

Status: deferred

Revisit when:

- public-availability timing is sufficiently complete
- acceptance and availability timestamps can be validated across the required reporting set

## Enforcement Reminder

Until the deferred items above are revisited, the repo should keep emphasizing:

- canonical identity
- PIT correctness
- generated-only compatibility bridges
- reproducible dataset/export build references
- fail-closed verification
- narrow, disciplined tooling expansion
- one cleanup authority rather than overlapping cleanup inventories
