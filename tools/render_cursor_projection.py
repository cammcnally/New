from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.cursor_projection import build_cursor_projection, render_cursor_projection
from tools.repo_authority_common import tracked_files
from tools.refresh_projection_lock import refresh_projection_lock


def main() -> int:
    check_mode = "--check" in sys.argv

    if check_mode:
        projection = build_cursor_projection(PROJECT_ROOT)
        drifted: list[str] = []
        expected_cursor_files = set(projection)
        actual_cursor_files = {path for path in tracked_files() if path.startswith(".cursor/")}
        for relative_path, expected_content in projection.items():
            target = PROJECT_ROOT / relative_path
            expected = expected_content.rstrip() + "\n"
            if not target.exists():
                drifted.append(f"missing: {relative_path}")
                continue
            actual = target.read_text(encoding="utf-8")
            if actual != expected:
                drifted.append(f"drifted: {relative_path}")
        extra_cursor_files = sorted(actual_cursor_files - expected_cursor_files)
        if extra_cursor_files:
            drifted.extend(f"unexpected: {relative_path}" for relative_path in extra_cursor_files)
        if drifted:
            print("Generated cursor projection has drifted from canonical sources:", file=sys.stderr)
            for item in drifted:
                print(f"  {item}", file=sys.stderr)
            print("\nRun 'python tools/render_cursor_projection.py' to regenerate.", file=sys.stderr)
            return 1
        print("Cursor projection is up to date.")
        return 0

    created = render_cursor_projection(PROJECT_ROOT)
    refresh_projection_lock(PROJECT_ROOT)
    print(json.dumps({"rendered_files": [str(path.relative_to(PROJECT_ROOT)) for path in created]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
