from __future__ import annotations

import json
from pathlib import Path

from control_plane.cursor_projection import build_projection_manifest_payload

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def refresh_projection_lock(project_root: Path | None = None) -> Path:
    root = (project_root or PROJECT_ROOT).resolve()
    lock_path = root / "contracts" / "projection_manifest.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(build_projection_manifest_payload(root), indent=2) + "\n",
        encoding="utf-8",
    )
    return lock_path


def main() -> int:
    path = refresh_projection_lock()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
