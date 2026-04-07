#!/usr/bin/env bash
# Configure core.hooksPath to .githooks for this clone. Run from repo root:
#   bash tools/setup_repo_git_hooks.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
git config core.hooksPath .githooks
configured="$(git config --get core.hooksPath || true)"
if [ "$configured" != ".githooks" ]; then
  echo "error: core.hooksPath is '${configured:-empty}'; expected .githooks" >&2
  exit 1
fi
echo "OK: core.hooksPath=$configured"
echo "Pre-commit uses: uv run pre-commit run --hook-stage pre-commit"
echo "Auto-push requires REPO_AUTO_PUSH_ENABLED=1; see docs/repo_sync_policy.md"
