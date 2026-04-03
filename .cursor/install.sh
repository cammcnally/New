#!/usr/bin/env bash
set -euxo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

export HOME="${HOME:-/root}"
export PATH="${HOME}/.local/bin:${PATH}"
export PYTHONUNBUFFERED=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export UV_LINK_MODE=copy
export PIPELINE_BASE_PATH="${REPO_ROOT}"

if ! command -v curl >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y curl
  else
    apt-get update
    apt-get install -y curl
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv python install 3.11.9

if [ -x ".venv/bin/python" ]; then
  CURRENT_VENV_PYTHON="$("./.venv/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  if [ "${CURRENT_VENV_PYTHON}" != "3.11.9" ]; then
    rm -rf .venv
  fi
fi

uv venv --python 3.11.9 .venv
uv sync --frozen --group dev --group control-plane --group ingestion --group ingestion-test

./.venv/bin/python - <<'PY'
import os
import sys

assert sys.version.startswith("3.11.9"), sys.version
assert os.path.isdir(".venv"), ".venv missing"
print(sys.version)
PY
