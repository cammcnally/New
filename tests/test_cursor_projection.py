from __future__ import annotations

import json
from pathlib import Path

from control_plane.cursor_projection import build_cursor_projection


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cursor_projection_matches_repo_shims() -> None:
    projection = build_cursor_projection(PROJECT_ROOT)
    for relative_path, expected_content in projection.items():
        target = PROJECT_ROOT / relative_path
        assert target.exists(), f"Missing projected shim: {relative_path}"
        actual = target.read_text(encoding="utf-8")
        assert actual == expected_content.rstrip() + "\n"


def test_projection_manifest_source_of_truth_is_agents_md() -> None:
    manifest = json.loads((PROJECT_ROOT / ".cursor" / "projection_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_of_truth"] == "AGENTS.md"


def test_projected_cursor_skills_are_non_canonical() -> None:
    text = (PROJECT_ROOT / ".cursor" / "skills" / "phase1-validation-runbook" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "This local skill file is non-canonical." in text
