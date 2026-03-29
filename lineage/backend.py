from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


class FileTransport:
    """Writes OpenLineage events as JSON files under ``output_dir``."""

    def __init__(self, output_dir: str = "lineage_events") -> None:
        self.output_dir = output_dir

    def emit(self, event: dict[str, Any]) -> str:
        """Serialize ``event`` to ``{output_dir}/{run_id}_{event_type}_{timestamp}.json``."""
        os.makedirs(self.output_dir, exist_ok=True)
        run_id = str((event.get("run") or {}).get("runId") or "unknown_run")
        event_type = str(event.get("eventType") or "UNKNOWN")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_type = event_type.replace(os.sep, "_")
        path = os.path.join(self.output_dir, f"{run_id}_{safe_type}_{ts}.json")
        payload = json.dumps(event, indent=2, sort_keys=True, default=str)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
        return path
