#!/usr/bin/env python3
"""Print reproduction hints from ops/overnight/issues.seed.json by issue id."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_id", help="e.g. E2E-001")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    seed_path = root / "ops" / "overnight" / "issues.seed.json"
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    for item in data.get("issues", []):
        if item.get("id") == args.issue_id:
            print(f"id:          {item.get('id')}")
            print(f"priority:    {item.get('priority')}")
            print(f"title:       {item.get('title')}")
            print(f"repro_hint:  {item.get('repro_hint')}")
            print(f"success:     {item.get('success_criteria')}")
            if item.get("notes"):
                print(f"notes:       {item.get('notes')}")
            return 0

    print(f"unknown issue id: {args.issue_id}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
