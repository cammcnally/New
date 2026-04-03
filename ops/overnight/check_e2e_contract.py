#!/usr/bin/env python3
"""Validate on-disk artifacts against ops/overnight/e2e_contract.json (file-only gate; no hooks)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_LFS = "version https://git-lfs.github.com/spec/v1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_contract(root: Path) -> dict[str, Any]:
    path = root / "ops" / "overnight" / "e2e_contract.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.readline().strip() == _LFS
    except OSError:
        return False


def _check_artifact(root: Path, rule: dict[str, Any], *, errors: list[str]) -> None:
    rel = rule["path"]
    path = (root / rel).resolve()
    must_exist = rule.get("must_exist", False) or rule.get("must_exist_after_claimed_dev_green", False)
    if must_exist and not path.is_file():
        errors.append(f"missing required file: {rel}")
        return
    if not path.is_file():
        return
    if rule.get("must_not_be_git_lfs_pointer") and _is_lfs_pointer(path):
        errors.append(f"file is Git LFS pointer, not hydrated data: {rel}")
    min_bytes = rule.get("min_bytes")
    if min_bytes is not None and path.stat().st_size < int(min_bytes):
        errors.append(f"file too small ({path.stat().st_size} < {min_bytes}): {rel}")
    keys = rule.get("json_keys_required")
    if keys:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON: {rel}: {exc}")
            return
        for key in keys:
            if key not in data:
                errors.append(f"JSON missing key {key!r}: {rel}")


def _check_run_status_dev_green(root: Path, contract: dict[str, Any], *, errors: list[str]) -> None:
    templates = contract.get("path_templates", {})
    rel = templates.get("run_status_json", "data_lake/manifests/run_status.json")
    path = root / rel
    if not path.is_file():
        errors.append(f"missing run_status (required for dev-green claim): {rel}")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"invalid run_status JSON: {exc}")
        return
    status = data.get("status")
    if status not in ("completed", "partial_progress"):
        errors.append(f"run_status.status must be completed or partial_progress, got {status!r}")

    required = contract.get("dev_green_required_stages", [])
    stages = data.get("stages") or []
    by_stage = {s.get("stage"): s.get("status") for s in stages if isinstance(s, dict)}
    for st in required:
        if by_stage.get(st) != "passed":
            errors.append(f"stage {st!r} not passed in run_status (got {by_stage.get(st)!r})")

    if status == "partial_progress" and by_stage.get("export_panel") != "passed":
        errors.append(
            "partial_progress dev-green requires export_panel passed (typical: --stop-after export_panel)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("dev-green", "contract-info"),
        default="dev-green",
        help="dev-green validates DEV_EXPORT_SPINE_GREEN artifacts; contract-info prints contract id and exits 0",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    contract = _load_contract(root)

    if args.mode == "contract-info":
        print(json.dumps({"contract_id": contract.get("contract_id"), "schema": contract.get("schema_version")}))
        return 0

    errors: list[str] = []
    for rule in contract.get("artifact_requirements_dev_green", []):
        if isinstance(rule, dict):
            _check_artifact(root, rule, errors=errors)

    _check_run_status_dev_green(root, contract, errors=errors)

    if errors:
        print("[e2e-contract] FAILED", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print("[e2e-contract] OK dev-green checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
