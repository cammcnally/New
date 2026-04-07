#!/usr/bin/env python3
"""Generate repo inventory: tracked, untracked (non-ignored), ignored summary; duplicates report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

import yaml  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
REGISTRY_YAML = PROJECT_ROOT / "repo_control" / "file_registry.yaml"
AUTHORITY_YAML = PROJECT_ROOT / "config" / "canonical" / "repo_authority.yaml"
OUT_DIR = PROJECT_ROOT / "artifacts" / "repo_inventory"
MAX_HASH_BYTES = 32 * 1024 * 1024
HASH_PREFIX_LEN = 16


def _normalize(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


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


def _excluded_from_walk(rel: str) -> bool:
    n = _normalize(rel)
    return n.startswith(".repo_runtime/backups/") or n == ".repo_runtime" or n.startswith(".repo_runtime/")


def _file_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return path.suffix.lower() or "no_extension"


def _sha256_file(path: Path) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > MAX_HASH_BYTES:
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _load_file_registry_entries() -> list[dict[str, Any]]:
    payload = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise SystemExit("file_registry.yaml missing entries list")
    return [e for e in entries if isinstance(e, dict)]


def _registry_match(path: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        pattern = str(entry.get("path", ""))
        if fnmatch(_normalize(path), _normalize(pattern)):
            return entry
    return None


def _authority_buckets(path: str, authority: dict[str, Any]) -> list[str]:
    from tools.repo_authority_common import classify_path

    try:
        return classify_path(path, authority)
    except SystemExit:
        return []


def _collect_ignored_summary(include_details: bool) -> dict[str, Any]:
    """Parse `git status --porcelain=1 --ignored` for !! entries."""
    result = subprocess.run(
        ["git", "status", "--porcelain=1", "--ignored"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {"error": "git status failed", "stderr": result.stderr.strip()}
    top_level: dict[str, int] = defaultdict(int)
    samples: list[str] = []
    for line in result.stdout.splitlines():
        if not line.startswith("!! "):
            continue
        raw = line[3:].strip().strip('"')
        rel = _normalize(raw)
        top = rel.split("/")[0] if "/" in rel else rel
        top_level[top] += 1
        if include_details and len(samples) < 200:
            samples.append(rel)
    return {
        "top_level_counts": dict(sorted(top_level.items(), key=lambda x: (-x[1], x[0]))),
        "sample_paths": samples if include_details else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate repo inventory JSON under artifacts/repo_inventory/.")
    parser.add_argument(
        "--include-ignored-details",
        action="store_true",
        help="Include up to 200 sample ignored paths in addition to top-level counts.",
    )
    args = parser.parse_args()

    from tools.repo_authority_common import load_repo_authority_registry, normalize_path, tracked_files

    authority = load_repo_authority_registry(AUTHORITY_YAML)
    reg_entries = _load_file_registry_entries()

    tracked = [p for p in tracked_files() if not _excluded_from_walk(p)]
    untracked_raw = _git_lines("ls-files", "--others", "--exclude-standard")
    untracked = [normalize_path(p) for p in untracked_raw if not _excluded_from_walk(p)]

    hash_to_paths: dict[str, list[str]] = defaultdict(list)

    entries_out: list[dict[str, Any]] = []

    def process_path(rel: str, bucket: str) -> None:
        abs_path = PROJECT_ROOT / rel
        auth = _authority_buckets(rel, authority)
        reg = _registry_match(rel, reg_entries)
        ftype = _file_type(abs_path) if abs_path.exists() else "missing"
        if reg:
            classification = str(reg.get("class", "unknown"))
            risk = "low" if reg.get("review_required") is False else "medium"
            rec = f"registry cleanup_policy={reg.get('cleanup_policy', '')}"
        elif auth:
            classification = auth[0]
            risk = "low"
            rec = "matches repo_authority bucket"
        else:
            classification = "unknown_manual_review"
            risk = "medium"
            rec = "manual review; not matched by file_registry patterns"

        sha = None
        if abs_path.is_file():
            sha = _sha256_file(abs_path)
            if sha:
                hash_to_paths[sha].append(rel)

        entries_out.append(
            {
                "path": rel,
                "bucket": bucket,
                "file_type": ftype,
                "authority_buckets": auth,
                "registry_class": reg.get("class") if reg else None,
                "registry_cleanup_policy": reg.get("cleanup_policy") if reg else None,
                "classification": classification,
                "risk": risk,
                "recommended_action": rec,
                "sha256": sha,
            }
        )

    for rel in sorted(tracked):
        process_path(rel, "tracked")
    for rel in sorted(untracked):
        process_path(rel, "untracked_visible")

    exact_groups = [sorted(set(paths)) for paths in hash_to_paths.values() if len(paths) > 1]

    # Same size + SHA-256 prefix but differing full hash: report-only (weak heuristic).
    prefix_groups: dict[tuple[int, str], list[str]] = defaultdict(list)
    for rel in tracked + untracked:
        ap = PROJECT_ROOT / rel
        if not ap.is_file():
            continue
        sha = _sha256_file(ap)
        if not sha:
            continue
        try:
            sz = ap.stat().st_size
        except OSError:
            continue
        prefix_groups[(sz, sha[:HASH_PREFIX_LEN])].append(rel)

    near_candidates: list[dict[str, Any]] = []
    for key, paths in prefix_groups.items():
        unique_hashes = set()
        for rel in paths:
            ap = PROJECT_ROOT / rel
            h = _sha256_file(ap)
            if h:
                unique_hashes.add(h)
        if len(paths) > 1 and len(unique_hashes) > 1:
            near_candidates.append(
                {
                    "size": key[0],
                    "hash_prefix": key[1],
                    "paths": sorted(set(paths)),
                    "note": "report_only_no_delete_recommendation",
                }
            )

    ignored_summary = _collect_ignored_summary(args.include_ignored_details)

    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buckets": {
            "tracked_count": len(tracked),
            "untracked_visible_count": len(untracked),
            "ignored_summary": ignored_summary,
        },
        "excluded_globs": [".repo_runtime/backups/**"],
        "entries": entries_out,
        "exact_duplicate_groups": exact_groups,
        "near_duplicate_candidates": near_candidates,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_ts = OUT_DIR / f"inventory_{ts}.json"
    out_latest = OUT_DIR / "inventory_latest.json"
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    out_ts.write_text(text, encoding="utf-8")
    out_latest.write_text(text, encoding="utf-8")
    print(f"wrote {out_ts.relative_to(PROJECT_ROOT)}")
    print(f"wrote {out_latest.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
