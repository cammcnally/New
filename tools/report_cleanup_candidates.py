from __future__ import annotations

import argparse
import json
import subprocess
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

import yaml  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "repo_control" / "file_registry.yaml"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "repo_cleanup_report.json"
TEXT_FILE_SUFFIXES = {
    ".md",
    ".py",
    ".json",
    ".jsonl",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".csv",
    ".sql",
}


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


def _normalize(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _matches(path: str, pattern: str) -> bool:
    normalized_pattern = _normalize(pattern)
    normalized_path = _normalize(path)
    return fnmatch(normalized_path, normalized_pattern)


def _load_registry_entries() -> list[dict[str, Any]]:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("file registry must contain a non-empty entries list")
    return entries


def _match_entry(path: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if _matches(path, str(entry["path"])):
            return entry
    return None


def _text_file_paths(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for rel in paths:
        path = PROJECT_ROOT / rel
        if path.is_file() and path.suffix.lower() in TEXT_FILE_SUFFIXES:
            files.append(path)
    return files


def _referenced_elsewhere(candidate: str, search_files: list[Path]) -> bool:
    for path in search_files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if candidate in text:
            return True
    return False


def _recommendation(
    *,
    unregistered_tracked_files: list[str],
    files_requiring_human_review: list[dict[str, Any]],
    delete_candidates: list[dict[str, Any]],
) -> str:
    if unregistered_tracked_files:
        return "registry backfill incomplete; register remaining tracked files before cleanup decisions"
    if files_requiring_human_review:
        return "review flagged compatibility-only and optional-secondary surfaces before deleting anything"
    if delete_candidates:
        return "safe to remove obvious runtime-output junk only; keep tracked review-first candidates pending human confirmation"
    return "registry coverage is clean; no immediate cleanup action required beyond routine runtime-output deletion"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report repo cleanup candidates from the file registry.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path to write JSON cleanup report",
    )
    args = parser.parse_args(argv)

    entries = _load_registry_entries()
    tracked_files = [_normalize(path) for path in _git_lines("ls-files")]
    untracked_files = [_normalize(path) for path in _git_lines("ls-files", "--others", "--exclude-standard")]
    search_files = _text_file_paths(tracked_files)

    unregistered_tracked_files = [path for path in tracked_files if _match_entry(path, entries) is None]

    vital_files_summary: list[str] = []
    generated_files_summary: list[str] = []
    compatibility_only_files_summary: list[str] = []
    delete_candidates: list[dict[str, Any]] = []
    archive_candidates: list[dict[str, Any]] = []
    files_requiring_human_review: list[dict[str, Any]] = []
    stale_but_referenced: list[dict[str, Any]] = []

    for path in tracked_files:
        entry = _match_entry(path, entries)
        if entry is None:
            continue
        file_class = str(entry["class"])
        cleanup_policy = str(entry["cleanup_policy"])
        record = {
            "path": path,
            "class": file_class,
            "cleanup_policy": cleanup_policy,
            "reason": str(entry["reason"]),
        }
        if file_class in {"canonical", "normative_doc"}:
            vital_files_summary.append(path)
        if file_class == "generated":
            generated_files_summary.append(path)
        if file_class == "compatibility_only":
            compatibility_only_files_summary.append(path)
        if cleanup_policy == "archive" or file_class == "evidence_archive":
            archive_candidates.append(record)
        if cleanup_policy in {"delete_if_unreferenced", "review_first"} and file_class in {"compatibility_only", "optional_secondary", "delete_candidate"}:
            files_requiring_human_review.append(record)
            if _referenced_elsewhere(path, search_files):
                stale_but_referenced.append(record)

    known_runtime_delete_patterns = (
        "outputs/",
        "data_lake/",
        "pipeline_outputs/",
        "mlruns/",
        ".local/",
    )
    untracked_worktree_files: list[dict[str, Any]] = []
    for path in untracked_files:
        entry = _match_entry(path, entries)
        item = {
            "path": path,
            "matched_registry_path": entry["path"] if entry else None,
            "classification": entry["class"] if entry else "review_required",
        }
        untracked_worktree_files.append(item)
        if entry and str(entry["cleanup_policy"]) in {"delete_on_sight", "regenerate"}:
            delete_candidates.append(
                {
                    "path": path,
                    "class": str(entry["class"]),
                    "cleanup_policy": str(entry["cleanup_policy"]),
                    "reason": f"matches registry path {entry['path']}",
                }
            )
        elif any(path.startswith(prefix) for prefix in known_runtime_delete_patterns):
            delete_candidates.append(
                {
                    "path": path,
                    "class": "ignore_runtime_output",
                    "cleanup_policy": "delete_on_sight",
                    "reason": "matches known local runtime output pattern",
                }
            )

    report = {
        "generated_at_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "registry_path": str(REGISTRY_PATH.relative_to(PROJECT_ROOT).as_posix()),
        "vital_files_summary": sorted(vital_files_summary),
        "generated_files_summary": sorted(generated_files_summary),
        "compatibility_only_files_summary": sorted(compatibility_only_files_summary),
        "unregistered_tracked_files": sorted(unregistered_tracked_files),
        "untracked_worktree_files": sorted(untracked_worktree_files, key=lambda item: item["path"]),
        "delete_candidates": sorted(delete_candidates, key=lambda item: item["path"]),
        "archive_candidates": sorted(archive_candidates, key=lambda item: item["path"]),
        "files_requiring_human_review": sorted(files_requiring_human_review, key=lambda item: item["path"]),
        "stale_but_referenced": sorted(stale_but_referenced, key=lambda item: item["path"]),
        "final_cleanup_recommendation": _recommendation(
            unregistered_tracked_files=unregistered_tracked_files,
            files_requiring_human_review=files_requiring_human_review,
            delete_candidates=delete_candidates,
        ),
    }

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"cleanup_report_written {output_path}")
    print(f"unregistered_tracked_files={len(unregistered_tracked_files)}")
    print(f"untracked_worktree_files={len(untracked_worktree_files)}")
    print(f"delete_candidates={len(delete_candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
