#!/usr/bin/env python3
"""Emit a short Markdown summary from optional structured attempt files in ops/overnight/out/."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--attempt-json",
        default=None,
        help="Path to attempt payload JSON (default: ops/overnight/out/attempt.json)",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    path = Path(args.attempt_json) if args.attempt_json else root / "ops" / "overnight" / "out" / "attempt.json"

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Overnight attempt summary",
        "",
        f"- generated_at_utc: `{now}`",
        "",
    ]

    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        lines.append("## Recorded attempt")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(payload, indent=2))
        lines.append("```")
    else:
        lines.append("## Recorded attempt")
        lines.append("")
        lines.append(f"_No file at `{path}` — agents should write structured JSON there after each loop._")
        lines.append("")
        lines.append("Suggested keys: `issue_id`, `commands_run`, `check_e2e_contract_exit`, `keep_or_discard`, `notes`.")

    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
