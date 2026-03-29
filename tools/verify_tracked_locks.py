from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.policy_loader import (
    build_policy_fingerprint_lock_payload,
    compute_loader_manifest_hash,
    compute_policy_fingerprint_from_payload,
    load_canonical_policy_payload,
)


def main() -> int:
    bootstrap_path = PROJECT_ROOT / "contracts" / "bootstrap_pin.lock.json"
    policy_path = PROJECT_ROOT / "contracts" / "policy_fingerprint.lock.json"
    projection_path = PROJECT_ROOT / "contracts" / "projection_manifest.lock.json"
    for path in (bootstrap_path, policy_path, projection_path):
        if not path.exists():
            raise SystemExit(f"Missing tracked lock file: {path}")

    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    if not all(isinstance(payload, dict) for payload in (bootstrap, policy, projection)):
        raise SystemExit("One or more tracked lock files are not JSON objects")

    canonical_payload = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    expected_fingerprint = compute_policy_fingerprint_from_payload(canonical_payload)
    expected_manifest_hash = compute_loader_manifest_hash(PROJECT_ROOT)
    expected_policy_lock = build_policy_fingerprint_lock_payload(PROJECT_ROOT, canonical_payload)

    if bootstrap.get("policy_fingerprint") != expected_fingerprint:
        raise SystemExit("Bootstrap lock policy fingerprint mismatch")
    if bootstrap.get("loader_manifest_hash") != expected_manifest_hash:
        raise SystemExit("Bootstrap lock loader manifest hash mismatch")
    if policy != expected_policy_lock:
        raise SystemExit("Policy fingerprint lock mismatch")
    if projection.get("generated_by") != "tools/render_cursor_projection.py":
        raise SystemExit("Projection lock generated_by mismatch")
    if projection.get("source_of_truth") != "AGENTS.md":
        raise SystemExit("Projection lock source_of_truth mismatch")
    if projection.get("canonical_skill_root") != ".agents/skills":
        raise SystemExit("Projection lock canonical_skill_root mismatch")

    print("tracked_locks_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
