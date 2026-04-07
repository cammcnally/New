from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.repo_authority_common import (
    FROZEN_HASHES_PATH,
    load_frozen_hashes,
    load_repo_authority_registry,
    normalize_path,
    registry_patterns,
    tracked_files,
)

ALLOWED_CHANGE_CATEGORIES = {
    "manifest_hookup",
    "compatibility_artifact_path_hookup",
    "benchmark_side_artifact_consumption",
    "approved_bug_fix",
}
FREEZE_BYPASS_MARKER = "FREEZE_BYPASS_APPROVED"
FREEZE_ALLOWED_PREFIX = "FREEZE_ALLOWED:"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_files() -> list[str]:
    registry = load_repo_authority_registry()
    patterns = registry_patterns(registry, "frozen_boundary_only")
    matches = {
        tracked
        for tracked in tracked_files()
        if any(PathMatcher.matches(tracked, pattern) for pattern in patterns)
    }
    return sorted(matches)


class PathMatcher:
    @staticmethod
    def matches(path: str, pattern: str) -> bool:
        from tools.repo_authority_common import path_matches

        return path_matches(path, pattern)


def _extract_categories(text: str) -> set[str]:
    categories: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == FREEZE_BYPASS_MARKER:
            categories.add("approved_bug_fix")
            continue
        if line.startswith(FREEZE_ALLOWED_PREFIX):
            category = line.split(":", 1)[1].strip()
            if category:
                categories.add(category)
    return categories


def collect_errors(project_root: Path | None = None) -> list[str]:
    if project_root is not None and project_root.resolve() != PROJECT_ROOT:
        raise SystemExit("verify_frozen_boundaries.py only supports the current project root")

    load_repo_authority_registry()
    frozen_payload = load_frozen_hashes()
    if frozen_payload.get("version") != 1:
        raise SystemExit(f"{normalize_path(FROZEN_HASHES_PATH)} must contain version=1")
    entries = frozen_payload.get("entries")
    if not isinstance(entries, dict):
        raise SystemExit(f"{normalize_path(FROZEN_HASHES_PATH)} must contain an entries object")

    failures: list[str] = []
    frozen_files = _frozen_files()
    missing_registry_files = [path for path in frozen_files if path not in entries]
    if missing_registry_files:
        raise SystemExit(
            "Frozen boundary baseline missing entries: " + ", ".join(sorted(missing_registry_files))
        )

    for relative in frozen_files:
        path = PROJECT_ROOT / relative
        if not path.exists():
            failures.append(f"path={relative} rule=missing_frozen_surface")
            continue
        expected_entry = entries.get(relative)
        if not isinstance(expected_entry, dict):
            failures.append(f"path={relative} rule=invalid_frozen_hash_entry")
            continue
        expected_hash = expected_entry.get("sha256")
        if not isinstance(expected_hash, str) or not expected_hash:
            failures.append(f"path={relative} rule=missing_sha256")
            continue
        current_hash = _sha256(path)
        if current_hash == expected_hash:
            continue
        text = path.read_text(encoding="utf-8")
        categories = _extract_categories(text)
        invalid_categories = sorted(category for category in categories if category not in ALLOWED_CHANGE_CATEGORIES)
        if invalid_categories:
            failures.append(
                f"path={relative} rule=invalid_freeze_category categories={','.join(invalid_categories)}"
            )
            continue
        if not categories:
            failures.append(
                f"path={relative} rule=frozen_hash_mismatch expected={expected_hash} actual={current_hash}"
            )
            continue
        allowed = expected_entry.get("allowed_change_categories", [])
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            failures.append(f"path={relative} rule=invalid_allowed_change_categories")
            continue
        if not categories.issubset(set(allowed)):
            failures.append(
                f"path={relative} rule=disallowed_freeze_category categories={','.join(sorted(categories))}"
            )
            continue

    return failures


def main() -> int:
    failures = collect_errors(PROJECT_ROOT)
    frozen_files = _frozen_files()

    if failures:
        print("Frozen boundary violations detected:")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1)

    print(f"frozen_boundaries_ok files={len(frozen_files)} registry={normalize_path(FROZEN_HASHES_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
