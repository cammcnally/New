from __future__ import annotations

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
