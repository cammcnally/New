from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from tools.verify_market_data_common import project_root
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_common import project_root


REQUIRED_DOCS = {"README.md", "docs/data_contract.md", "market_data/COMMANDS.md"}
MATERIAL_PREFIXES = (
    "market_data/",
    "mlflow_integration/",
    ".github/workflows/",
    "tools/verify_market_data",
)
MATERIAL_FILES = {
    "Makefile",
    ".codex/hooks.json",
    "dvc.yaml",
    "configs/benchmarks.yaml",
    "market_data/COMMANDS.md",
    "Pipeline.py",
    "tools/run_repo_e2e.py",
}


def _run_git(args: list[str]) -> list[str]:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=project_root(),
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise SystemExit(f"[docs-sync] git command failed: {' '.join(args)} :: {stderr}")
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def changed_files(*, base_ref: str | None, explicit_files: list[str]) -> list[str]:
    if explicit_files:
        return [Path(path).as_posix() for path in explicit_files]
    if base_ref:
        return _run_git(["git", "diff", "--name-only", f"{base_ref}...HEAD"])
    tracked = _run_git(["git", "diff", "--name-only", "HEAD"])
    untracked = _run_git(["git", "ls-files", "--others", "--exclude-standard"])
    return sorted(set(tracked + untracked))


def _is_material_change(path: str) -> bool:
    if path in REQUIRED_DOCS:
        return False
    if path in MATERIAL_FILES:
        return True
    return path.startswith(MATERIAL_PREFIXES)


def run_checks(*, base_ref: str | None = None, files: list[str] | None = None) -> int:
    files = files or []
    changed = changed_files(base_ref=base_ref, explicit_files=files)
    material = sorted(path for path in changed if _is_material_change(path))

    if not material:
        print("[docs-sync] no material market-data changes detected")
        return 0

    changed_docs = set(changed) & REQUIRED_DOCS
    missing = sorted(REQUIRED_DOCS - changed_docs)
    if missing:
        raise SystemExit(
            "[docs-sync] material changes require updated docs. "
            f"Changed material files: {material}. Missing docs: {missing}"
        )

    print(f"[docs-sync] material changes detected and docs updated: {sorted(changed_docs)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce market-data documentation synchronization.")
    parser.add_argument("--base-ref", default=None, help="Base git ref for change detection")
    parser.add_argument("--file", dest="files", action="append", default=[], help="Explicit changed file path")
    args = parser.parse_args(argv)
    return run_checks(base_ref=args.base_ref, files=args.files)


if __name__ == "__main__":
    raise SystemExit(main())
