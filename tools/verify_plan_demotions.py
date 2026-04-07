from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.repo_authority_common import (
    DEMOTION_BANNER,
    load_repo_authority_registry,
    normalize_path,
    path_matches,
    registry_patterns,
    tracked_files,
)

MANDATORY_SCAN_PATTERNS = (
    "docs/plans/**",
    "docs/checklists/**",
    "docs/workplans/**",
    "docs/archive_candidates/**",
)


def _candidate_files() -> list[str]:
    registry = load_repo_authority_registry()
    patterns = list(dict.fromkeys((*MANDATORY_SCAN_PATTERNS, *registry_patterns(registry, "merge_demote_candidates"))))
    matches: set[str] = set()
    for tracked in tracked_files():
        if any(path_matches(tracked, pattern) for pattern in patterns):
            matches.add(tracked)
    for pattern in patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file():
                matches.add(normalize_path(path.relative_to(PROJECT_ROOT)))
    return sorted(matches)


def main() -> int:
    failures: list[str] = []
    candidates = _candidate_files()
    for relative in candidates:
        path = PROJECT_ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith(DEMOTION_BANNER):
            failures.append(relative)
    if failures:
        print("Missing required demotion banner:")
        for relative in failures:
            print(f"  path={relative} rule=missing_demotion_banner")
        raise SystemExit(1)
    print(f"plan_demotions_ok files={len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
