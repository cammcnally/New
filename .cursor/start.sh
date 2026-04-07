#!/usr/bin/env bash
set -euxo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

export HOME="${HOME:-/root}"
export PATH="${HOME}/.local/bin:${PATH}"
export PYTHONUNBUFFERED=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIPELINE_BASE_PATH="${REPO_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Run .cursor/install.sh first." >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo ".venv is missing. Run .cursor/install.sh first." >&2
  exit 1
fi

VENV_PYTHON_VERSION="$("./.venv/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if [ "${VENV_PYTHON_VERSION}" != "3.11.9" ]; then
  echo "Expected .venv Python 3.11.9, found ${VENV_PYTHON_VERSION}. Re-run .cursor/install.sh." >&2
  exit 1
fi

./.venv/bin/python -m pip --version >/dev/null
uv run python --version
