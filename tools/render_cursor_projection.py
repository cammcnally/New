from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.cursor_projection import render_cursor_projection
from tools.refresh_projection_lock import refresh_projection_lock


def main() -> int:
    created = render_cursor_projection(PROJECT_ROOT)
    refresh_projection_lock(PROJECT_ROOT)
    print(json.dumps({"rendered_files": [str(path.relative_to(PROJECT_ROOT)) for path in created]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
