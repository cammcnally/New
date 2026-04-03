from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.repo_authority_common import FROZEN_HASHES_PATH, load_frozen_hashes
from tools.verify_frozen_boundaries import collect_errors, main as verify_frozen_boundaries_main

PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.regression


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_frozen_boundaries_verifier_passes_for_repo_state() -> None:
    assert verify_frozen_boundaries_main() == 0
    assert collect_errors(PROJECT_ROOT) == []


def test_frozen_registry_covers_pipeline_py() -> None:
    payload = load_frozen_hashes()
    entries = payload["entries"]
    assert "Pipeline.py" in entries
    assert set(entries["Pipeline.py"]["allowed_change_categories"]) == {
        "manifest_hookup",
        "compatibility_artifact_path_hookup",
        "benchmark_side_artifact_consumption",
        "approved_bug_fix",
    }


def test_pipeline_py_matches_committed_baseline() -> None:
    payload = json.loads(FROZEN_HASHES_PATH.read_text(encoding="utf-8"))
    expected_hash = payload["entries"]["Pipeline.py"]["sha256"]
    actual_hash = _sha256(PROJECT_ROOT / "Pipeline.py")
    assert actual_hash == expected_hash
