from __future__ import annotations

from pathlib import Path

import pytest

from tools.repo_authority_common import (
    DEMOTION_BANNER,
    GENERATED_AUTHORITY_PATTERNS,
    MANDATORY_BUCKET_VALUES,
    classify_path,
    file_text_lines,
    load_repo_authority_registry,
    normalize_path,
    path_matches,
    registry_patterns,
    tracked_files,
)
from tools.verify_repo_authority import (
    CI_WORKFLOW_RELATIVE,
    GOVERNED_EXACT,
    GOVERNED_PREFIXES,
    REPO_GOVERNANCE_WORKFLOW_RELATIVE,
    collect_errors,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.regression
TEXT_SCAN_SUFFIXES = {".json", ".md", ".mdc", ".txt", ".yaml", ".yml"}


def _generated_paths(registry: dict[str, object]) -> list[str]:
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


def _merge_demote_candidates(registry: dict[str, object]) -> list[str]:
    patterns = list(registry_patterns(registry, "merge_demote_candidates"))
    matches: set[str] = set()
    for relative in tracked_files():
        if any(path_matches(relative, pattern) for pattern in patterns):
            matches.add(relative)
    for pattern in patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file():
                matches.add(normalize_path(path.relative_to(PROJECT_ROOT)))
    return sorted(matches)


def test_repo_authority_verifier_passes_for_repo_state() -> None:
    assert collect_errors(PROJECT_ROOT) == []


def test_protected_authorities_are_declared() -> None:
    registry = load_repo_authority_registry()
    protected = set(registry["protected_authorities"])
    assert set(MANDATORY_BUCKET_VALUES["protected_authorities"]).issubset(protected)


def test_generated_surfaces_are_not_authoritative() -> None:
    registry = load_repo_authority_registry()
    for relative_path in _generated_paths(registry):
        if Path(relative_path).suffix.lower() not in TEXT_SCAN_SUFFIXES:
            continue
        for line in file_text_lines(PROJECT_ROOT / relative_path):
            assert not any(pattern.search(line) for pattern in GENERATED_AUTHORITY_PATTERNS), relative_path


def test_work_plan_files_carry_demotion_banners() -> None:
    registry = load_repo_authority_registry()
    for relative_path in _merge_demote_candidates(registry):
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert text.startswith(DEMOTION_BANNER), relative_path


def test_governed_surfaces_are_classified() -> None:
    registry = load_repo_authority_registry()
    for relative in tracked_files():
        if relative in GOVERNED_EXACT or relative.startswith(GOVERNED_PREFIXES):
            assert classify_path(relative, registry), relative


def test_main_ci_invokes_repo_governance() -> None:
    ci_text = (PROJECT_ROOT / CI_WORKFLOW_RELATIVE).read_text(encoding="utf-8")
    assert REPO_GOVERNANCE_WORKFLOW_RELATIVE in ci_text
