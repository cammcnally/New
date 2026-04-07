# Repository audit specification

## Purpose

Operational guide for **human- and tool-driven** audits. It does **not** replace machine-readable authority.

## Registry of record (do not duplicate)

- Path classification and enforcement: [`config/canonical/repo_authority.yaml`](../config/canonical/repo_authority.yaml)
- File vitality and cleanup policy: [`repo_control/file_registry.yaml`](../repo_control/file_registry.yaml)
- Policy framing: [`docs/governance/REPO_AUTHORITY_POLICY.md`](governance/REPO_AUTHORITY_POLICY.md)

## Audit scope

- Tracked committed paths (`git ls-files`)
- Untracked, non-ignored paths (`git ls-files --others --exclude-standard`)
- Ignored-path **summary** only (counts / top-level buckets)—not a deletion catalog

Excluded from default inventory walks:

- `.repo_runtime/backups/**` (ignored mirror clones; non-authoritative)

## Classification taxonomy (procedural)

| Class | Meaning |
|-------|---------|
| **canonical_authority** | Governing prose or config; must not be superseded by ad hoc docs |
| **active_source** | Production code, tests, CI, tools in active use |
| **compatibility_surface** | Bridge / transitional paths required by consumers |
| **generated_artifact** | Regenerated outputs; prefer refresh over hand edit |
| **archive** | Historical evidence; no runtime authority |
| **temporary** | Short-lived local or session output |
| **duplicate_superseded** | Same role as another file; needs explicit demotion/supersession |
| **unknown_manual_review** | No safe auto-classification |

Map procedural classes to `repo_authority.yaml` buckets and `file_registry.yaml` entries when recording actions.

## Auto-fix vs quarantine vs never auto-delete

| Situation | Allowed auto-action (pass 1) |
|-----------|------------------------------|
| Exact duplicate content hash | Report as **review / dedupe candidate** only |
| Near-duplicate (size/partial hash/fuzzy) | **Report-only**; no merge/delete recommendation without semantic or reference evidence (imports, docs links, explicit `file_registry` supersession) |
| Paths with `cleanup_policy: delete_on_sight` in `file_registry` | May delete only when verifier + audit log entry exist and scope is explicit |
| Protected / frozen / authority surfaces | **Never** auto-delete |
| Uncertain | **Quarantine or log** in [`docs/repo_audit_log.md`](repo_audit_log.md); no delete |

## Validation and stop conditions

Stop and escalate when:

- `make verify` or `uv run python tools/run_verify_bundle.py` fails
- Any proposed deletion touches `protected_authorities`, `frozen_boundary_only`, or `control_plane/**` without explicit approval
- Remote operations hit branch protection, permissions, or open PRs (capture exact command output)

## Tracked `.cursor/plans`

Only plans that pass `verify_generated_surfaces` authority-leak scans should be tracked under `.cursor/plans/`. Heavier planning documents with phrases like “canonical authority” belong under `docs/plans/` or remain untracked, or CI will fail on generated-surface scans.

## Related

- Sync and hooks: [`docs/repo_sync_policy.md`](repo_sync_policy.md)
- Live log: [`docs/repo_audit_log.md`](repo_audit_log.md)
