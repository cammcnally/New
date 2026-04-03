# Overnight program (agent-facing)

Your only valid objective is to move the repository toward an honest **`DEV_EXPORT_SPINE_GREEN`** state as defined in [`e2e_contract.json`](e2e_contract.json) and [`e2e_definition.md`](e2e_definition.md), unless the issue you picked explicitly targets full E2E through `finalize_status`.

Do not report partial success as full end-to-end success.

## Short-term scope: fix when you find it

**Default behavior is remediation, not cataloging.** When you hit a failure, inconsistency, or contract violation while working the critical path, **fix it at the root** (or make the dependency explicit and unblock it) in the same session whenever it is safe and in-policy. Do not stop at only adding notes to logs, issue lists, or docs unless the blocker is **externally impossible** or **explicitly out of scope**—then document with evidence and the minimum next action.

## Read first

1. `.cursor/rules/` overnight pack (`overnight-e2e-repair`, `no-fake-e2e-success`, `critical-path-priority`, `mandatory-root-cause-debugging`).
2. `AGENTS.md` (canonical JSON policy + Agent policy).
3. This directory: `e2e_definition.md`, `e2e_contract.json`, `issues.seed.json`.

## Loop (one iteration)

1. Pick the **highest-priority** unresolved item from `issues.seed.json` (or the human-maintained queue) that lies on the critical path to the contract.
2. **Reproduce** the failure with the smallest command (see `run_repro.py` or issue notes).
3. **Root-cause** fix only; no speculative rewrites.
4. Run **targeted** tests or verifiers for the touched surface.
5. If you touched the canonical E2E path, configs, bridge, or market-data orchestration: run  
   `uv run python ops/overnight/check_e2e_contract.py --mode dev-green`  
   after a real local run when artifacts exist.
6. Write **structured outputs** under `ops/overnight/out/` (gitignored): see `summarize_run.py` and `audit_decision.md`.
7. Mark **keep** or **discard** with evidence in your handoff.

## Invalid changes

A change is **invalid** if it:

- weakens tests or assertions,
- bypasses PIT or schema checks (or compat/bridge gates) for canonical claims,
- uses stale artifacts to simulate progress,
- replaces a real stage with a stub or no-op,
- edits the E2E contract or definition to fit broken behavior instead of fixing the code or data path.

Fix only the **highest-priority** critical-path blocker unless that blocker is externally blocked or non-reproducible (then document and stop).
