from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.cursor_projection import build_cursor_projection, build_projection_manifest_payload
from tools.repo_authority_common import (
    GENERATED_AUTHORITY_PATTERNS,
    file_text_lines,
    load_repo_authority_registry,
    normalize_path,
    path_matches,
    registry_patterns,
    tracked_files,
)
from tools.verify_tracked_locks import main as verify_tracked_locks_main

EXPECTED_LOCK_FILES = {
    "contracts/bootstrap_pin.lock.json",
    "contracts/policy_fingerprint.lock.json",
    "contracts/projection_manifest.lock.json",
}
TEXT_SCAN_SUFFIXES = {".json", ".md", ".mdc", ".txt", ".yaml", ".yml"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _resolve_manifest_output(manifest_path: Path, payload: dict[str, object]) -> Path | None:
    candidates: list[Path] = []
    if manifest_path.name.endswith(".manifest.json"):
        candidates.append(manifest_path.with_name(manifest_path.name[: -len(".manifest.json")]))
    output_path = payload.get("output_path")
    if isinstance(output_path, str) and output_path:
        candidates.append(PROJECT_ROOT / Path(output_path).name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _cursor_projection_failures(root: Path) -> list[str]:
    projection = {relative: content.rstrip() + "\n" for relative, content in build_cursor_projection(root).items()}
    expected_cursor_files = set(projection)
    actual_cursor_files = {path for path in tracked_files() if path.startswith(".cursor/")}

    failures: list[str] = []
    missing_cursor = sorted(expected_cursor_files - actual_cursor_files)
    extra_cursor = sorted(actual_cursor_files - expected_cursor_files)
    if missing_cursor:
        failures.append(f"rule=missing_projected_cursor_files paths={missing_cursor}")
    if extra_cursor:
        failures.append(f"rule=unexpected_tracked_cursor_files paths={extra_cursor}")

    for relative_path, expected_content in projection.items():
        path = root / relative_path
        if not path.exists():
            failures.append(f"path={relative_path} rule=missing_generated_projection")
            continue
        actual_content = path.read_text(encoding="utf-8")
        if actual_content != expected_content:
            failures.append(f"path={relative_path} rule=generated_projection_drift")

    manifest_path = root / ".cursor" / "projection_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_manifest = build_projection_manifest_payload(root)
        if manifest != expected_manifest:
            failures.append(f"path=.cursor/projection_manifest.json rule=projection_manifest_drift")
    return failures


def _lock_file_failures() -> list[str]:
    failures: list[str] = []
    lock_files = {path for path in tracked_files() if path.startswith("contracts/") and path.endswith(".lock.json")}
    missing_locks = sorted(EXPECTED_LOCK_FILES - lock_files)
    extra_locks = sorted(lock_files - EXPECTED_LOCK_FILES)
    if missing_locks:
        failures.append(f"rule=missing_lock_files paths={missing_locks}")
    if extra_locks:
        failures.append(f"rule=unexpected_lock_files paths={extra_locks}")
    try:
        verify_tracked_locks_main()
    except SystemExit as exc:
        message = str(exc).strip() or "tracked lock verification failed"
        failures.append(f"rule=lock_artifact_drift detail={message}")
    return failures


def _manifest_and_export_failures(registry: dict[str, object]) -> list[str]:
    failures: list[str] = []
    for relative_path in _generated_paths(registry):
        path = PROJECT_ROOT / relative_path
        if not path.exists() or not relative_path.endswith(".manifest.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"path={relative_path} rule=invalid_manifest_json detail={exc}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"path={relative_path} rule=manifest_not_object")
            continue
        output_path = _resolve_manifest_output(path, payload)
        if output_path is None:
            failures.append(f"path={relative_path} rule=stale_manifest_missing_output")
            continue
        expected_hash = payload.get("content_hash")
        if not isinstance(expected_hash, str) or not expected_hash:
            failures.append(f"path={relative_path} rule=missing_content_hash")
            continue
        actual_hash = _sha256(output_path)
        if actual_hash != expected_hash:
            failures.append(
                f"path={relative_path} rule=stale_generated_export output={normalize_path(output_path.relative_to(PROJECT_ROOT))}"
            )
    return failures


def _authority_leak_failures(registry: dict[str, object]) -> list[str]:
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


def collect_errors(project_root: Path | None = None) -> list[str]:
    root = (project_root or PROJECT_ROOT).resolve()
    if root != PROJECT_ROOT:
        raise SystemExit("verify_generated_surfaces.py only supports the current project root")

    registry = load_repo_authority_registry()
    errors: list[str] = []
    errors.extend(_cursor_projection_failures(root))
    errors.extend(_lock_file_failures())
    errors.extend(_manifest_and_export_failures(registry))
    errors.extend(_authority_leak_failures(registry))
    return errors


def run_checks(project_root: Path | None = None) -> int:
    errors = collect_errors(project_root)
    if errors:
        raise SystemExit("generated surface drift detected:\n- " + "\n- ".join(errors))
    print("generated_surfaces_ok")
    return 0


def main() -> int:
    return run_checks()


if __name__ == "__main__":
    raise SystemExit(main())
