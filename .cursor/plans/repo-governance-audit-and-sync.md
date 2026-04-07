# Repo governance, hooks, remote sync, and audit (execution reference)

This file is a **tracked working copy** of the tightened governance plan. Canonical procedure lives in `docs/repo_sync_policy.md`, `docs/repo_audit_spec.md`, and `docs/repo_audit_log.md`.

## Summary

- **E-drive-only** writes under `E:\stock_csvs_AI-Perspective\NEW\`.
- **No `git push --mirror`** for publishing; mirror **clone** backups live under **ignored** `.repo_runtime/backups/`.
- **Hooks**: `core.hooksPath=.githooks`; `pre-commit` stage uses `--hook-stage pre-commit`; `pre-push` runs pre-commit pre-push + `make verify`.
- **Auto-push**: `post-commit` / `post-rewrite` push only when `REPO_AUTO_PUSH_ENABLED=1`.
- **Inventory**: tracked + untracked (non-ignored) + optional ignored summary; exclude `.repo_runtime/backups/**`.
- **Remote deletes**: explicit allowlist (default `{main}`); log `origin/HEAD` and candidates before `git push origin --delete`.
- **Near-duplicates**: report-only in pass 1.

## Phases

1. Projection + `.gitignore` + `file_registry` + render.
2. `.pre-commit-config.yaml` + `.githooks` pre-commit / pre-push.
3. Inventory tool + first artifact + audit log entries.
4. Remote: mirror backup → fetch prune → allowlist deletes → `force-with-lease` main if applicable.
5. Enable auto-push via env var after validation is green.
