from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from control_plane.cursor_projection import build_cursor_projection, build_projection_manifest_payload
from tools.repo_authority_common import (
    GENERATED_AUTHORITY_PATTERNS,
    file_text_lines,
    load_repo_authority_registry,
    normalize_path,
    path_matches,
    registry_patterns,
    tracked_files,
)
from tools.verify_generated_surfaces import collect_errors
from tools.verify_tracked_locks import main as verify_tracked_locks_main

PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.regression
TEXT_SCAN_SUFFIXES = {".json", ".md", ".mdc", ".txt", ".yaml", ".yml"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _generated_paths() -> list[str]:
    registry = load_repo_authority_registry()
    patterns = list(registry_patterns(registry, "generated_shims"))
    patterns.extend(registry_patterns(registry, "generated_outputs"))
    matches: set[str] = set()
    for relative in tracked_files():
        if any(path_matches(relative, pattern) for pattern in patterns):
            matches.add(relative)
    for pattern in patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file():
                matches.add(normalize_path(path.relative_to(PROJECT_ROOT)))
    return sorted(matches)


def test_generated_surface_verifier_passes_for_repo_state() -> None:
    assert collect_errors(PROJECT_ROOT) == []


def test_cursor_projection_is_current() -> None:
    projection = build_cursor_projection(PROJECT_ROOT)
    for relative_path, expected_content in projection.items():
        actual = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert actual == expected_content.rstrip() + "\n"
    manifest = json.loads((PROJECT_ROOT / ".cursor" / "projection_manifest.json").read_text(encoding="utf-8"))
    assert manifest == build_projection_manifest_payload(PROJECT_ROOT)


def test_generated_manifest_and_export_are_current() -> None:
    manifest_path = PROJECT_ROOT / "panel_ohlcv_clean.csv.manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    export_path = PROJECT_ROOT / "panel_ohlcv_clean.csv"
    assert payload["content_hash"] == _sha256(export_path)


def test_generated_surfaces_are_not_marked_authoritative() -> None:
    for relative_path in _generated_paths():
        if Path(relative_path).suffix.lower() not in TEXT_SCAN_SUFFIXES:
            continue
        for line in file_text_lines(PROJECT_ROOT / relative_path):
            assert not any(pattern.search(line) for pattern in GENERATED_AUTHORITY_PATTERNS), relative_path


def test_tracked_locks_verifier_passes_for_repo_state() -> None:
    assert verify_tracked_locks_main() == 0
