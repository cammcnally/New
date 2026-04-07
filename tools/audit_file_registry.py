from __future__ import annotations

import subprocess
import sys
from datetime import date
from fnmatch import fnmatch
from pathlib import PurePosixPath, Path
from typing import Any

import yaml  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "repo_control" / "file_registry.yaml"

ALLOWED_CLASSES = {
    "canonical",
    "normative_doc",
    "compatibility_only",
    "generated",
    "generated_shims",
    "optional_secondary",
    "deferred_planned",
    "evidence_archive",
    "local_only",
    "delete_candidate",
    "ignore_runtime_output",
}
ALLOWED_AUTHORITIES = {
    "authoritative",
    "compatibility",
    "generated",
    "evidence_only",
    "local_only",
    "pending_review",
}
ALLOWED_OWNER_LAYERS = {
    "market_data",
    "pipeline",
    "docs",
    "control_plane",
    "ci",
    "tests",
    "tooling",
    "local_runtime",
    "agents",
    "ide",
}
ALLOWED_CLEANUP_POLICIES = {
    "keep",
    "regenerate",
    "archive",
    "delete_if_unreferenced",
    "delete_on_sight",
    "review_first",
}
REQUIRED_FIELDS = (
    "path",
    "class",
    "authority",
    "owner_layer",
    "cleanup_policy",
    "regeneration_source",
    "review_required",
    "reason",
    "last_reviewed",
)


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise SystemExit(f"Missing file registry: {REGISTRY_PATH}")
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("file registry must be a YAML object")
    return payload


def _normalize(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _matches(path: str, pattern: str) -> bool:
    normalized_pattern = _normalize(pattern)
    normalized_path = _normalize(path)
    return fnmatch(normalized_path, normalized_pattern)


def _validate_entry(entry: dict[str, Any], *, index: int) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in entry]
    if missing:
        raise SystemExit(f"registry entry {index} missing fields: {missing}")
    if entry["class"] not in ALLOWED_CLASSES:
        raise SystemExit(f"registry entry {index} has invalid class: {entry['class']}")
    if entry["authority"] not in ALLOWED_AUTHORITIES:
        raise SystemExit(f"registry entry {index} has invalid authority: {entry['authority']}")
    if entry["owner_layer"] not in ALLOWED_OWNER_LAYERS:
        raise SystemExit(f"registry entry {index} has invalid owner_layer: {entry['owner_layer']}")
    if entry["cleanup_policy"] not in ALLOWED_CLEANUP_POLICIES:
        raise SystemExit(f"registry entry {index} has invalid cleanup_policy: {entry['cleanup_policy']}")
    if not isinstance(entry["review_required"], bool):
        raise SystemExit(f"registry entry {index} review_required must be boolean")
    if not str(entry["reason"]).strip():
        raise SystemExit(f"registry entry {index} reason must be non-empty")
    try:
        date.fromisoformat(str(entry["last_reviewed"]))
    except ValueError as exc:
        raise SystemExit(f"registry entry {index} last_reviewed must be ISO date: {exc}") from exc


def main() -> int:
    payload = _load_registry()
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("file registry must contain a non-empty entries list")

    normalized_patterns: set[str] = set()
    for idx, raw_entry in enumerate(entries, start=1):
        if not isinstance(raw_entry, dict):
            raise SystemExit(f"registry entry {idx} must be an object")
        _validate_entry(raw_entry, index=idx)
        pattern = _normalize(str(raw_entry["path"]))
        if pattern in normalized_patterns:
            raise SystemExit(f"duplicate registry path pattern: {pattern}")
        normalized_patterns.add(pattern)

    tracked_files = [_normalize(path) for path in _git_lines("ls-files")]
    unmatched = [path for path in tracked_files if not any(_matches(path, str(entry["path"])) for entry in entries)]
    if unmatched:
        sample = ", ".join(unmatched[:10])
        raise SystemExit(f"unregistered tracked files detected ({len(unmatched)}): {sample}")

    try:
        registry_label = REGISTRY_PATH.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        registry_label = str(REGISTRY_PATH)
    print(
        f"file_registry_ok entries={len(entries)} tracked_files={len(tracked_files)} "
        f"registry={registry_label}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
