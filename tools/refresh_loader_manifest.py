from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "control_plane" / "loader_manifest.json"
TRACKED_FILES = [
    "AGENTS.md",
    "control_plane/models.py",
    "control_plane/task_state.py",
    "control_plane/codex_mcp.py",
    "control_plane/orchestrator.py",
    "control_plane/runtime_env.py",
    "control_plane/policy_loader.py",
    "control_plane/governance_registries.json",
    "control_plane/cursor_projection.py",
    "tools/control_plane.py",
    "tools/render_cursor_projection.py",
    "tools/migrate_repo_env.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refresh_loader_manifest(project_root: Path | None = None) -> Path:
    root = (project_root or PROJECT_ROOT).resolve()
    files: dict[str, str] = {}
    for relative in TRACKED_FILES:
        path = root / relative
        if not path.exists():
            raise SystemExit(f"Missing protected file for loader manifest: {relative}")
        files[relative] = sha256_file(path)
    payload = {
        "generated_by": "tools/refresh_loader_manifest.py",
        "files": files,
    }
    manifest_path = root / "control_plane" / "loader_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    path = refresh_loader_manifest()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
