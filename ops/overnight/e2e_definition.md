# End-to-end definition (this repository)

This file is the **human-readable** companion to [`e2e_contract.json`](e2e_contract.json). The JSON file is authoritative for machine checks.

## What "authoritative E2E" means here

The repo's canonical orchestrated flow is `uv run python tools/run_repo_e2e.py`, with stages defined in `market_data/orchestration/e2e.py`:

1. `dependency_sync`
2. `canonical_market_data`
3. `verify_market_data` (docs sync, contracts, PIT, compat)
4. `export_panel` (compatibility CSV + sidecar manifest + bridge checks)
5. `pipeline_run` (`Pipeline.py`)
6. `finalize_status` (sanity check + verification summary)

See [`docs/implementation_runbook.md`](../../docs/implementation_runbook.md) and [`docs/e2e-run-blockers.md`](../../docs/e2e-run-blockers.md).

## DEV-scale green (`DEV_EXPORT_SPINE_GREEN`)

For early enablement work **without** claiming full research pipeline completion, the overnight contract [`e2e_contract.json`](e2e_contract.json) defines **`DEV_EXPORT_SPINE_GREEN`**: a **real** run through `export_panel` with all guards through bridge, stopped there (`--stop-after export_panel`).

That is **not** the same as full E2E through `finalize_status`. Do not report it as full E2E.

## It counts as honest DEV green only if

- The canonical command (or equivalent with documented args) was run and exited without cheating per the contract.
- Required artifacts exist, are non-trivial in size, and the panel is not a Git LFS pointer file.
- The export sidecar manifest includes `dataset_build_id`, `export_panel_version_id`, and `universe_filter_applied`.
- `run_status.json` (under `data_lake/manifests/`) reflects the claimed stages; for dev green, `partial_progress` with successful completion through `export_panel` is acceptable when using `--stop-after export_panel`.
- Validations were not weakened to obtain green.

## It does not count if

- Exit code is 0 but stages were skipped or faked.
- Outputs are placeholders, empty panels, or reused stale artifacts presented as a new run.
- PIT, schema, compat, or bridge checks were bypassed for the claimed path.
- The contract file was edited to redefine success downward for the same claim.

## Hardline (no hooks)

**Hardline here means instruction-mandatory and contract-validated, not hook-enforced.** There is no guarantee an agent will comply; morning review uses artifacts and `check_e2e_contract.py` output.
