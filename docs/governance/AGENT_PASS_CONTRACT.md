# Agent Pass Contract

## Purpose

Every agent-driven issue pass must produce one reviewable, machine-checkable packet before the next issue is allowed to proceed.

This contract is repo-wide governance for issue-by-issue execution. It does not supersede `AGENTS.md`, frozen Phase 1 docs, or `config/canonical/repo_authority.yaml`.

## Canonical Surfaces

- Human-readable lifecycle and operator workflow: `docs/governance/AGENT_PASS_CONTRACT.md`
- Machine-readable policy: `config/canonical/pass_contract_policy.json`
- Exact report template: `config/canonical/pass_contract_report_template.json`
- Runtime helper: `tools/pass_contract.py`
- Verifier and local gates: `tools/verify_pass_contract.py`

## Packet Location

Per-issue runtime packets live under `.local/pass_contract/`:

- active issue pointer: `.local/pass_contract/current_issue.json`
- closeout history: `.local/pass_contract/history.jsonl`
- per-issue report: `.local/pass_contract/issues/<issue_id>/pass_report.json`

This path is correct for this repo because durable local automation state already lives under `.local/control_plane/`. The mechanism remains repo-tracked through canonical docs, policy, scripts, tests, hooks, and CI, while the per-pass packet stays local and does not pollute tracked authority registries.

## Required Report Fields

Each issue pass report must contain these contract fields:

- `issue_id`
- `objective`
- `planned_files`
- `protected_or_frozen_surface_touch`
- `acceptance_criteria`
- `files_changed`
- `plain_english_diff_summary`
- `commands_run`
- `command_results`
- `artifacts_produced`
- `unresolved_items`
- `not_touched`
- `separate_approval_needed`
- `protected_surface_drift_check`
- `final_gate_decision`

The exact JSON skeleton lives in `config/canonical/pass_contract_report_template.json`.

## Lifecycle

### 1. Start the pass before editing

Create the packet and lock the scope:

```bash
uv run python tools/pass_contract.py start --issue-id <ISSUE_ID> --objective "<objective>" --touches-protected-or-frozen yes|no --planned-file <path> --acceptance "<criterion>"
```

The start command records:

- exact issue ID
- exact planned files
- whether protected or frozen surfaces are declared in scope
- exact acceptance criteria
- a baseline snapshot of the current dirty governed surfaces

### 2. Execute one issue only

During the pass:

- do not widen `planned_files`
- do not bundle cleanup or opportunistic refactors
- do not touch undeclared protected or frozen surfaces

### 3. Fill the evidence before closeout

Update the report with:

- plain-English diff summary
- exact commands run
- exact raw command results
- artifacts produced
- unresolved items
- not-touched items
- separate approvals still needed
- acceptance-criteria results
- final gate decision and reason

### 4. Verify the active packet

Use the verifier before closing:

```bash
uv run python tools/verify_pass_contract.py --active
```

### 5. Close the pass before commit or push

Close the pass after the report is complete and before advancing:

```bash
uv run python tools/pass_contract.py close --issue-id <ISSUE_ID>
```

Closeout captures the effective `files_changed`, checks for mixed-scope drift against the recorded baseline, appends the history log, and clears the active issue pointer only if the packet is valid.

## Stop/Go Rules

`final_gate_decision` must be exactly one of:

- `STOP`
- `GO FOR NEXT ISSUE`

`GO FOR NEXT ISSUE` is legal only when all of the following are true:

- every acceptance criterion is marked satisfied
- required verification commands were run and passed
- no changed file falls outside `planned_files`
- no unexpected protected or frozen surface drift occurred
- `unresolved_items` is empty
- `separate_approval_needed` is empty

The verifier must fail closed when any of those checks fail.

## Local Enforcement

The strongest repo-trackable local blockers in this repo are:

- `pre-commit`: blocks staged governed changes when no active pass exists or staged paths exceed the declared scope
- `pre-push`: blocks pushes when the active pass is still open or the latest closed pass is not `GO FOR NEXT ISSUE`
- Codex `SessionStart`: blocks starting a new issue when the latest closed pass ended in `STOP`
- repo-local verifier command: `uv run python tools/verify_pass_contract.py --policy-only`

Cursor itself cannot be hard-blocked here in a repo-tracked way, so Cursor receives a generated compatibility rule derived from canonical sources rather than a hand-maintained authority file.

## Verification Commands

For this contract surface itself, use:

- `uv run python tools/verify_pass_contract.py --policy-only`
- `uv run python -m pytest tests/test_pass_contract.py tests/acceptance/test_pass_contract_wiring.py -q`

Broader governance changes should still run the normal repo governance commands when the touched paths require them.

## Limitations

This system can deterministically block repo-local starts, commits, and pushes only where the toolchain exposes real hooks or verifier entrypoints. It cannot force every external editor or every human workflow to comply. Where hard in-editor blocking is unavailable, the repo uses the strongest hybrid available:

- canonical spec
- machine-readable policy
- exact template
- verifier
- repo-local hooks
- generated Cursor compatibility surface
- CI failure gate
