from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.repo_authority_common import (
    DEMOTION_BANNER,
    GENERATED_AUTHORITY_PATTERNS,
    MANDATORY_ENFORCEMENT_SENTENCE,
    REQUIRED_BUCKETS,
    SECONDARY_DOC_PATHS,
    SECONDARY_DOC_SELF_CLAIM_PATTERNS,
    classify_path,
    file_text_lines,
    load_repo_authority_registry,
    normalize_path,
    path_matches,
    registry_patterns,
    tracked_files,
)
from tools.verify_frozen_boundaries import collect_errors as collect_frozen_boundary_errors

REPO_AUTHORITY_POLICY_RELATIVE = "docs/governance/REPO_AUTHORITY_POLICY.md"
CI_WORKFLOW_RELATIVE = ".github/workflows/ci.yml"
REPO_GOVERNANCE_WORKFLOW_RELATIVE = ".github/workflows/repo-governance.yml"
REQUIRED_ENFORCEMENT_SURFACES = (
    "tools/verify_repo_authority.py",
    "tools/verify_generated_surfaces.py",
    "tools/verify_frozen_boundaries.py",
    "tools/verify_plan_demotions.py",
    "tools/render_cursor_projection.py",
    "tests/acceptance/test_repo_authority.py",
    "tests/acceptance/test_generated_surfaces.py",
    "tests/acceptance/test_frozen_boundaries.py",
    REPO_GOVERNANCE_WORKFLOW_RELATIVE,
)
EXPECTED_AGENTS_PROTECTED_AUTHORITIES = [
    "AGENTS.md",
    "docs/data_contract.md",
    "docs/phase1-research-spec.md",
    "docs/phase1-execution-roadmap.md",
    "README.md",
]
EXPECTED_AGENTS_FROZEN_BOUNDARY = [
    "Pipeline.py",
    "tools/phase1_sanity_check.py",
    "feature_registry/*",
    "tests/test_phase1_*.py",
]
GOVERNED_PREFIXES = (
    "docs/",
    "market_data/",
    "control_plane/",
    "feature_registry/",
    "mlflow_integration/",
    "lineage/",
    "gx/",
    ".cursor/",
    ".github/workflows/",
    "tools/",
    "tests/",
    "contracts/",
    "config/",
    "configs/",
)
GOVERNED_EXACT = {
    "AGENTS.md",
    "README.md",
    "Pipeline.py",
    "Makefile",
    ".gitignore",
    ".gitattributes",
    ".python-version",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "dvc.yaml",
    "strategy-report.qmd",
}
DEMOTED_INTRO_FORBIDDEN_PHRASES = (
    "supersedes",
    "active working plan",
    "canonical working checklist",
    "normative implementation directive",
    "normative combined directive",
)
INTRO_LINE_LIMIT = 40
TEXT_SCAN_SUFFIXES = {".json", ".md", ".mdc", ".txt", ".yaml", ".yml"}


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_ref_exists(ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _git_deleted_paths(*diff_args: str) -> set[str]:
    deletions: set[str] = set()
    for raw_line in _git_lines("diff", "--name-status", "--diff-filter=D", *diff_args):
        parts = raw_line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] != "D":
            continue
        deletions.add(normalize_path(parts[1]))
    return deletions


def _git_deletion_ranges() -> list[str]:
    ranges: list[str] = []

    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base_ref:
        remote_base = f"origin/{base_ref}"
        if _git_ref_exists(remote_base):
            merge_base_lines = _git_lines("merge-base", "HEAD", remote_base)
            if merge_base_lines:
                ranges.append(f"{merge_base_lines[0]}...HEAD")

    before_ref = os.environ.get("GITHUB_EVENT_BEFORE", "").strip()
    if before_ref and before_ref != "0000000000000000000000000000000000000000" and _git_ref_exists(before_ref):
        ranges.append(f"{before_ref}...HEAD")

    if not ranges and _git_ref_exists("HEAD^"):
        ranges.append("HEAD^..HEAD")

    deduped: list[str] = []
    seen: set[str] = set()
    for diff_range in ranges:
        if diff_range in seen:
            continue
        seen.add(diff_range)
        deduped.append(diff_range)
    return deduped


def _git_deletions() -> list[str]:
    deletions: set[str] = set()
    for args in (
        tuple(),
        ("--cached",),
    ):
        deletions.update(_git_deleted_paths(*args))
    for diff_range in _git_deletion_ranges():
        deletions.update(_git_deleted_paths(diff_range))
    return sorted(deletions)


def _parse_agents_section(section_name: str) -> list[str]:
    lines = file_text_lines(PROJECT_ROOT / "AGENTS.md")
    capture = False
    values: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if raw_line.startswith("### "):
            if capture:
                break
            capture = stripped == section_name
            continue
        if not capture:
            continue
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
    return values


def _line_matches(relative_path: str, patterns: tuple[tuple[str, object], ...]) -> list[str]:
    path = PROJECT_ROOT / relative_path
    if not path.exists():
        return []
    intro_lines = file_text_lines(path)[:INTRO_LINE_LIMIT]
    failures: list[str] = []
    for idx, line in enumerate(intro_lines, start=1):
        for label, pattern in patterns:
            if pattern.search(line):
                failures.append(
                    f"path={relative_path} rule=protected_authority_contradiction match={label} line={idx}: {line.strip()}"
                )
    return failures


def _generated_paths(registry: dict[str, object]) -> list[str]:
    patterns = list(registry_patterns(registry, "generated_shims"))
    patterns.extend(registry_patterns(registry, "generated_outputs"))
    matches: set[str] = set()
    for tracked in tracked_files():
        if any(path_matches(tracked, pattern) for pattern in patterns):
            matches.add(tracked)
    for pattern in patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file():
                matches.add(normalize_path(path.relative_to(PROJECT_ROOT)))
    return sorted(matches)


def _generated_authority_failures(registry: dict[str, object]) -> list[str]:
    failures: list[str] = []
    for relative_path in _generated_paths(registry):
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            continue
        if path.suffix.lower() not in TEXT_SCAN_SUFFIXES:
            continue
        for idx, line in enumerate(file_text_lines(path), start=1):
            for pattern in GENERATED_AUTHORITY_PATTERNS:
                if pattern.search(line):
                    failures.append(
                        f"path={relative_path} rule=generated_surface_authority_leak match={pattern.pattern} line={idx}: {line.strip()}"
                    )
    return failures


def _governed_candidates() -> list[str]:
    candidates: list[str] = []
    for relative in tracked_files():
        if relative in GOVERNED_EXACT or relative.startswith(GOVERNED_PREFIXES):
            candidates.append(relative)
    return sorted(set(candidates))


def _undeclared_surface_failures(registry: dict[str, object]) -> list[str]:
    failures: list[str] = []
    for relative in _governed_candidates():
        if not classify_path(relative, registry):
            failures.append(f"path={relative} rule=undeclared_governed_surface")
    return failures


def _duplicate_authority_failures(registry: dict[str, object]) -> list[str]:
    failures: list[str] = []
    merge_patterns = registry_patterns(registry, "merge_demote_candidates")
    candidates: set[str] = set()
    for tracked in tracked_files():
        if any(path_matches(tracked, pattern) for pattern in merge_patterns):
            candidates.add(tracked)
    for pattern in merge_patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file():
                candidates.add(normalize_path(path.relative_to(PROJECT_ROOT)))
    for relative_path in sorted(candidates):
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith(DEMOTION_BANNER):
            failures.append(f"path={relative_path} rule=duplicate_authority_persistence missing_banner")
            continue
        intro_text = "\n".join(text.splitlines()[:20]).lower()
        for phrase in DEMOTED_INTRO_FORBIDDEN_PHRASES:
            if phrase in intro_text:
                failures.append(
                    f"path={relative_path} rule=duplicate_authority_persistence forbidden_phrase={phrase}"
                )
    return failures


def _workflow_wiring_failures() -> list[str]:
    failures: list[str] = []

    ci_text = (PROJECT_ROOT / CI_WORKFLOW_RELATIVE).read_text(encoding="utf-8")
    if REPO_GOVERNANCE_WORKFLOW_RELATIVE not in ci_text:
        failures.append(
            f"path={CI_WORKFLOW_RELATIVE} rule=missing_repo_governance_job target={REPO_GOVERNANCE_WORKFLOW_RELATIVE}"
        )

    workflow_text = (PROJECT_ROOT / REPO_GOVERNANCE_WORKFLOW_RELATIVE).read_text(encoding="utf-8")
    required_snippets = (
        "workflow_call:",
        "uv sync --group dev --group control-plane",
        "uv run python tools/verify_repo_authority.py",
        "uv run python tools/verify_generated_surfaces.py",
        "uv run python tools/verify_frozen_boundaries.py",
        "uv run python tools/render_cursor_projection.py --check",
        "uv run python tools/verify_plan_demotions.py",
        "uv run python -m pytest tests/acceptance/test_repo_authority.py -q",
        "uv run python -m pytest tests/acceptance/test_generated_surfaces.py -q",
        "uv run python -m pytest tests/acceptance/test_frozen_boundaries.py -q",
    )
    for snippet in required_snippets:
        if snippet not in workflow_text:
            failures.append(
                f"path={REPO_GOVERNANCE_WORKFLOW_RELATIVE} rule=missing_workflow_step snippet={snippet}"
            )

    return failures


def _deletion_failures(registry: dict[str, object]) -> list[str]:
    failures: list[str] = []
    for relative in _git_deletions():
        buckets = set(classify_path(relative, registry))
        if {"protected_authorities", "frozen_boundary_only", "live_runtime"} & buckets:
            failures.append(f"path={relative} rule=illegal_deletion protected_surface")
            continue
        if {"generated_shims", "generated_outputs"} & buckets:
            continue
        if "merge_demote_candidates" in buckets:
            continue
        failures.append(f"path={relative} rule=illegal_deletion unapproved_surface")
    return failures


def collect_errors(project_root: Path | None = None) -> list[str]:
    root = (project_root or PROJECT_ROOT).resolve()
    if root != PROJECT_ROOT:
        raise SystemExit("verify_repo_authority.py only supports the current project root")

    registry = load_repo_authority_registry()
    errors: list[str] = []

    for relative in REQUIRED_ENFORCEMENT_SURFACES:
        if not (PROJECT_ROOT / relative).exists():
            errors.append(f"path={relative} rule=missing_enforcement_surface")

    for path in (
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / REPO_AUTHORITY_POLICY_RELATIVE,
    ):
        text = path.read_text(encoding="utf-8")
        if MANDATORY_ENFORCEMENT_SENTENCE not in text:
            errors.append(
                f"path={normalize_path(path.relative_to(PROJECT_ROOT))} rule=missing_enforcement_sentence"
            )

    agents_text = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for required_heading in (
        "## Repository authority enforcement",
        "### Protected authorities",
        "### Frozen boundary",
        "### Generated surfaces",
        "### Duplicate authority rule",
        "### Deletion rule",
    ):
        if required_heading not in agents_text:
            errors.append(f"path=AGENTS.md rule=missing_heading heading={required_heading}")

    protected_from_agents = _parse_agents_section("### Protected authorities")
    expected_protected = EXPECTED_AGENTS_PROTECTED_AUTHORITIES
    if protected_from_agents != expected_protected:
        errors.append(
            f"path=AGENTS.md rule=protected_authorities_mismatch expected={expected_protected} actual={protected_from_agents}"
        )

    frozen_from_agents = _parse_agents_section("### Frozen boundary")
    if frozen_from_agents != EXPECTED_AGENTS_FROZEN_BOUNDARY:
        errors.append(
            "path=AGENTS.md rule=frozen_boundary_mismatch "
            f"expected={EXPECTED_AGENTS_FROZEN_BOUNDARY} actual={frozen_from_agents}"
        )

    generated_from_agents = _parse_agents_section("### Generated surfaces")
    expected_generated = [
        ".cursor/*",
        "contracts/*.lock.json",
        "manifests",
        "compatibility exports",
        "generated projections",
    ]
    if generated_from_agents != expected_generated:
        errors.append(
            f"path=AGENTS.md rule=generated_surfaces_mismatch expected={expected_generated} actual={generated_from_agents}"
        )

    policy_text = (PROJECT_ROOT / REPO_AUTHORITY_POLICY_RELATIVE).read_text(encoding="utf-8")
    for relative in REQUIRED_ENFORCEMENT_SURFACES:
        if relative not in policy_text:
            errors.append(
                f"path={REPO_AUTHORITY_POLICY_RELATIVE} rule=missing_enforcement_reference target={relative}"
            )

    for bucket in REQUIRED_BUCKETS:
        values = registry.get(bucket)
        if not isinstance(values, list) or not values:
            errors.append(f"path=config/canonical/repo_authority.yaml rule=empty_bucket bucket={bucket}")

    for relative in SECONDARY_DOC_PATHS:
        errors.extend(_line_matches(relative, SECONDARY_DOC_SELF_CLAIM_PATTERNS))

    errors.extend(_generated_authority_failures(registry))
    errors.extend(_duplicate_authority_failures(registry))
    errors.extend(_undeclared_surface_failures(registry))
    errors.extend(_workflow_wiring_failures())
    errors.extend(_deletion_failures(registry))

    for frozen_error in collect_frozen_boundary_errors(PROJECT_ROOT):
        errors.append(f"rule=frozen_boundary_violation {frozen_error}")

    return errors


def run_checks(project_root: Path | None = None) -> int:
    errors = collect_errors(project_root)
    if errors:
        raise SystemExit("repo authority drift detected:\n- " + "\n- ".join(errors))
    print("repo_authority_ok")
    return 0


def main() -> int:
    return run_checks()


if __name__ == "__main__":
    raise SystemExit(main())
