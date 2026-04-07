# Repo inventory artifacts

Machine-generated snapshots of repository path classification for audits.

## Outputs

| File | Description |
|------|-------------|
| `inventory_<UTC-timestamp>.json` | Point-in-time full payload |
| `inventory_latest.json` | Copy of the most recent run |

## Schema (summary)

Top-level keys:

- `generated_at_utc` — ISO-8601 UTC timestamp
- `buckets` — `tracked`, `untracked_visible`, `ignored_summary`
- `entries` — list of objects with: `path`, `bucket`, `file_type`, `authority_buckets` (from `repo_authority.yaml`), `registry_match` (from `file_registry.yaml` if any), `classification`, `risk`, `recommended_action`, `sha256` (when file is hashed)
- `exact_duplicate_groups` — lists of paths sharing the same `sha256` (tracked + untracked hashed files)
- `near_duplicate_candidates` — **report-only** pairs/groups (same size + hash prefix); no delete recommendation
- `excluded_globs` — e.g. `.repo_runtime/backups/**`

## Regeneration

From repository root:

```bash
uv run python tools/generate_repo_inventory.py
```

Optional: `--include-ignored-details` expands ignored reporting (still summary-oriented).

## Retention

Keep recent JSON files for evidence; large histories may be rotated by maintainers. Contents are **non-authoritative** relative to `config/canonical/repo_authority.yaml` and `repo_control/file_registry.yaml`.
