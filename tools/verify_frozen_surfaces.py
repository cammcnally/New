from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) in sys.path:
    sys.path.remove(str(TOOLS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.policy_loader import load_canonical_policy_payload

MANIFEST_PATH = PROJECT_ROOT / "contracts" / "frozen_surfaces_manifest.json"
PHASE1_CONTRACT_PATH = PROJECT_ROOT / "control_plane" / "phase1_contract.json"


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object at {path}")
    return payload


def _ensure_no_legacy_runtime_tokens(tracked_files: list[str]) -> None:
    offenders: list[str] = []
    for relative in tracked_files:
        path = PROJECT_ROOT / relative
        if path.suffix not in {".json", ".md", ".py", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "3.12.10" in text:
            offenders.append(relative)
    if offenders:
        raise SystemExit("Legacy runtime token 3.12.10 still present in: " + ", ".join(offenders))


def _ensure_runtime_contracts() -> None:
    if (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip() != "3.11.9":
        raise SystemExit(".python-version is not pinned to 3.11.9")
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'requires-python = ">=3.11.9,<3.12"' not in pyproject:
        raise SystemExit("pyproject.toml does not require >=3.11.9,<3.12")

    phase1_contract = _load_json(PHASE1_CONTRACT_PATH)
    python_contract = phase1_contract.get("python")
    if not isinstance(python_contract, dict):
        raise SystemExit("control_plane/phase1_contract.json is missing the python contract")
    if python_contract.get("min") != "3.11.9" or python_contract.get("max_exclusive") != "3.12.0":
        raise SystemExit("control_plane/phase1_contract.json does not encode the 3.11.9 runtime window")

    payload = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    runtime_environment = payload["runtime_environment"]
    if runtime_environment["required_python_version"] != "3.11.9":
        raise SystemExit("AGENTS.md runtime_environment is not pinned to 3.11.9")

    actions = payload["actions"]
    if actions["run_tests_all"]["command"] != ["python", "-m", "pytest", "-q"]:
        raise SystemExit("AGENTS.md run_tests_all is not using repo-local python -m pytest")
    if actions["run_tests_marker"]["command"] != ["python", "-m", "pytest", "-m", "{marker}"]:
        raise SystemExit("AGENTS.md run_tests_marker is not using repo-local python -m pytest")
    if actions["run_tests_scoped"]["command"] != ["python", "-m", "pytest", "-q", "{paths}"]:
        raise SystemExit("AGENTS.md run_tests_scoped is missing or incorrect")


def _ensure_no_bare_pytest_lines() -> None:
    readme_lines = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    bare_lines = [line for line in readme_lines if line.strip().startswith("pytest ")]
    if bare_lines:
        raise SystemExit("README.md still contains bare pytest entrypoints")


def main() -> int:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Missing manifest: {MANIFEST_PATH}")
    manifest = _load_json(MANIFEST_PATH)
    tracked = manifest.get("tracked_files")
    if not isinstance(tracked, list) or not tracked:
        raise SystemExit("frozen_surfaces_manifest.json must contain non-empty tracked_files")

    tracked_files = [str(item) for item in tracked]
    for relative in tracked_files:
        if not (PROJECT_ROOT / relative).exists():
            raise SystemExit(f"Missing frozen surface: {relative}")

    _ensure_no_legacy_runtime_tokens(tracked_files)
    _ensure_runtime_contracts()
    _ensure_no_bare_pytest_lines()
    print("frozen_surfaces_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
