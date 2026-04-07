# Repo Cleanup Policy

## Purpose

This document explains how the repo classifies files for vitality, cleanup, regeneration, and retirement.

The authoritative machine-readable source is `repo_control/file_registry.yaml`.

Rules:

- do not create a second cleanup authority beside the file registry
- use the registry to classify tracked files and important generated or local runtime surfaces
- use cleanup tooling to propose changes; do not guess from memory
- canonical and normative documentation files must never be auto-deleted

## Design Goal

The repo should stay simple and market-data-first.

Cleanup controls exist to:

- protect canonical market-data and Phase 1 authority surfaces
- distinguish compatibility-only and optional-secondary code from core runtime authority
- identify generated or local-only files that may be regenerated or deleted safely
- make file-count reduction a controlled process rather than an intuition-driven one

## Registry Fields

Each registry entry stores:

- `path`
- `class`
- `authority`
- `owner_layer`
- `cleanup_policy`
- `regeneration_source`
- `review_required`
- `reason`
- `last_reviewed`

Entries may be exact paths or patterns.

## Registry Classes

### `canonical`

Repo-vital code or configuration whose removal would change canonical behavior.

Examples:

- `market_data/**`
- `Pipeline.py`
- verification entrypoints under `tools/`

### `normative_doc`

Files that define semantics or operator expectations and must stay synchronized with code.

Examples:

- `README.md`
- `docs/data_contract.md`
- `docs/phase1-*.md`
- `AGENTS.md`

### `compatibility_only`

Files or outputs retained for legacy consumers and bridges. These must not gain new authority.

Examples:

- `market_data/bridge/**`
- generated panel exports
- compatibility-only identity adapters

### `generated`

Derived surfaces that may be regenerated and should not be hand-edited as live authority.

Examples:

- `contracts/*.lock.json`
- `.cursor/**`
- generated sidecar manifests

### `optional_secondary`

Useful but non-primary systems that may be reviewed for de-scoping if they add more maintenance burden than value.

Examples:

- `lineage/**`
- `gx/**`
- `dagster_pipeline/**`
- `dvc.yaml`

### `deferred_planned`

Tracked surfaces that represent planned or partially active work but are not current authority.

### `evidence_archive`

Historical evidence that should not be confused with live runtime authority.

### `local_only`

Machine-specific or runtime-specific surfaces that are not repo authority.

### `delete_candidate`

Files intentionally marked for retirement after validation.

### `ignore_runtime_output`

Ephemeral outputs that should be excluded from authority decisions and may usually be deleted immediately.

## Authority Values

- `authoritative`: active authority for behavior or governance
- `compatibility`: required for transitional consumers only
- `generated`: derived output
- `evidence_only`: historical or audit evidence
- `local_only`: machine-local runtime surface
- `pending_review`: not yet promoted to active authority

## Owner Layers

- `market_data`
- `pipeline`
- `docs`
- `control_plane`
- `ci`
- `tests`
- `tooling`
- `local_runtime`

## Cleanup Policies

### `keep`

Retain as an authoritative or repo-vital surface.

### `regenerate`

May be removed and recreated from its documented regeneration source.

### `archive`

Keep as historical evidence rather than as an active runtime surface.

### `delete_if_unreferenced`

Candidate for removal if no live references remain.

### `delete_on_sight`

Ephemeral or machine-local output that can be removed without review.

### `review_first`

Do not delete automatically; surface it for human review.

## Deletion Rules

- `canonical` and `normative_doc` files must never be auto-deleted
- automatic deletion is allowed only for entries classified as `generated`, `local_only`, or `ignore_runtime_output` with cleanup policy `regenerate` or `delete_on_sight`
- compatibility-only and optional-secondary files may be proposed for deletion, but only through review-oriented reporting
- untracked files should be treated as review-required unless they clearly match known runtime-output or temp patterns

## Workflow

### New tracked files

Every new tracked file should be covered by `repo_control/file_registry.yaml` before merge.

### Cleanup audit

Use:

```powershell
uv run python tools/audit_file_registry.py
uv run python tools/report_cleanup_candidates.py
```

The cleanup report should summarize:

- vital files
- generated files
- compatibility-only files
- untracked files
- delete candidates
- archive candidates
- files requiring human review
- stale-but-still-referenced surfaces

## Relationship To Existing Governance

- `contracts/frozen_surfaces_manifest.json` remains a narrow bootstrap existence subset, not a general cleanup registry
- `docs/contract-inventory.md` remains a human-readable contract and governance inventory
- `repo_control/file_registry.yaml` is the cleanup and vitality authority

If these surfaces disagree, update the stale description rather than adding another list.
