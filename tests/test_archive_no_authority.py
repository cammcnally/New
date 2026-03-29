"""Ensure archived docs and .local state cannot become canonical authority.

No Python module under control_plane/ or tools/ may reference docs/archive/
or .local/control_plane/ as a canonical (import/load) source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCANNED_DIRS = [
    ROOT / "control_plane",
    ROOT / "tools",
]

FORBIDDEN_PATTERNS = [
    "docs/archive",
    "docs\\archive",
    ".local/control_plane",
    ".local\\control_plane",
]


def _python_files():
    for d in SCANNED_DIRS:
        if d.is_dir():
            yield from d.rglob("*.py")


@pytest.mark.parametrize("py_file", list(_python_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_archive_imports(py_file: Path):
    """No control_plane/ or tools/ module may reference archived paths."""
    source = py_file.read_text(encoding="utf-8", errors="replace")
    for pattern in FORBIDDEN_PATTERNS:
        assert pattern not in source, (
            f"{py_file.relative_to(ROOT)} references archived path '{pattern}'. "
            f"Archived files under docs/archive/ and .local/control_plane/ "
            f"are evidence-only and must not be used as canonical sources."
        )


def test_archive_readme_exists():
    """The archive directory must contain a README documenting its non-authority status."""
    readme = ROOT / "docs" / "archive" / "README.md"
    assert readme.exists(), "docs/archive/README.md is missing"
    content = readme.read_text(encoding="utf-8")
    assert "read-only evidence" in content.lower(), (
        "docs/archive/README.md must state that archived files are read-only evidence"
    )
