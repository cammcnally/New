from __future__ import annotations

import platform
import sys
from pathlib import Path

REQUIRED = (3, 11, 9)
MAX_EXCLUSIVE = (3, 12, 0)


def main() -> int:
    current = tuple(sys.version_info[:3])
    if current < REQUIRED or current >= MAX_EXCLUSIVE:
        current_text = ".".join(str(part) for part in current)
        required_text = ".".join(str(part) for part in REQUIRED)
        raise SystemExit(
            f"Unsupported Python runtime: {current_text}. "
            f"Canonical runtime is >={required_text},<3.12 under the repo virtual environment."
        )
    repo_root = Path(__file__).resolve().parents[1]
    executable = Path(sys.executable).resolve()
    if repo_root not in executable.parents:
        raise SystemExit(f"Interpreter is not the repo-local virtual environment: {executable}")
    print(f"runtime_ok python={platform.python_version()} executable={executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
