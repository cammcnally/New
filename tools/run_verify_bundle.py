#!/usr/bin/env python3
"""Run the same checks as the Makefile `verify` target (portable; no `make` required)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

STEPS: list[list[str]] = [
    ["uv", "run", "python", "tools/verify_orchestration_authority.py"],
    ["uv", "run", "python", "tools/verify_runtime.py"],
    ["uv", "run", "python", "tools/verify_repo_authority.py"],
    ["uv", "run", "python", "tools/verify_generated_surfaces.py"],
    ["uv", "run", "python", "tools/verify_pass_contract.py", "--policy-only"],
    ["uv", "run", "python", "tools/verify_tracked_locks.py"],
    ["uv", "run", "python", "tools/verify_frozen_boundaries.py"],
    ["uv", "run", "python", "tools/verify_semantic_contracts.py"],
    ["uv", "run", "python", "tools/verify_plan_demotions.py"],
    ["uv", "run", "python", "tools/audit_file_registry.py"],
    [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        "tests/acceptance/test_repo_authority.py",
        "tests/acceptance/test_generated_surfaces.py",
        "tests/acceptance/test_frozen_boundaries.py",
        "tests/acceptance/test_pass_contract_wiring.py",
        "tests/acceptance/test_semantic_contracts.py",
        "-q",
    ],
]


def main() -> int:
    for cmd in STEPS:
        print(f"+ {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    print("verify_bundle_ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
