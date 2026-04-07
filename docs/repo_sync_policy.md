# Repository sync and Git hooks policy

## Scope

This document describes repo-scoped hooks under [`.githooks/`](../.githooks), configured via `git config core.hooksPath .githooks`. Use [`tools/setup_repo_git_hooks.ps1`](../tools/setup_repo_git_hooks.ps1) or [`tools/setup_repo_git_hooks.sh`](../tools/setup_repo_git_hooks.sh) from the repository root.

## What runs when

| Hook | Behavior |
|------|----------|
| `pre-commit` | `uv run pre-commit run --hook-stage pre-commit` (ruff, YAML checks, orchestration authority, pass-contract **pre-commit** gate, etc.). |
| `pre-push` | `uv run pre-commit run --hook-stage pre-push` then `uv run python tools/run_verify_bundle.py` (same steps as `make verify` in the [Makefile](../Makefile)). |
| `post-commit` | **No-op** unless `REPO_AUTO_PUSH_ENABLED=1`. If set and HEAD is not detached, `git push -u origin <current-branch>`. |
| `post-rewrite` | **No-op** unless `REPO_AUTO_PUSH_ENABLED=1`. If set and HEAD is not detached, `git push --force-with-lease origin <current-branch>`. |

## Committed state only

Only **committed** objects are pushed. Uncommitted working-tree changes are never sent to `origin` by these hooks.

## Why auto-push is gated

Pass-contract **pre-push** requires a closed latest report ending in `GO FOR NEXT ISSUE` (see [`docs/governance/AGENT_PASS_CONTRACT.md`](governance/AGENT_PASS_CONTRACT.md)). Full verify on pre-push can also fail mid-setup. To avoid failed pushes during repository surgery, **do not** set `REPO_AUTO_PUSH_ENABLED=1` until:

- remote cleanup (if any) is complete,
- hooks are installed,
- pass-contract wiring is restored,
- `make verify` (or `uv run python tools/run_verify_bundle.py`) is green.

Then enable auto-push deliberately, for example in PowerShell for the session:

```powershell
$env:REPO_AUTO_PUSH_ENABLED = "1"
```

Or persist in your profile only if you accept pushes after every successful commit.

## Force-push

Only `git push --force-with-lease` is used from `post-rewrite`, never bare `--force`.

## GitHub: delete head branches after merge

To reduce stale remote branches: **Repository → Settings → General → Pull Requests → Automatically delete head branches** (enable). Requires sufficient permissions on the repository.

## No mirror push

Do not use `git push --mirror` for publishing. Local mirror **clones** for backup live under ignored `.repo_runtime/backups/` (see [`docs/repo_audit_spec.md`](repo_audit_spec.md)).

## Windows and POSIX `sh`

Hooks under `.githooks` use `#!/bin/sh`. **Git for Windows** runs them with an MSYS `sh` when you use **Git Bash**. If `git push` fails inside `pre-push` with `Executable /bin/sh not found`, run Git from **Git Bash**, or ensure the Git MSYS `usr\\bin` directory is on `PATH` so `sh.exe` resolves. `pre-commit` also expects a POSIX shell for some local hooks.
