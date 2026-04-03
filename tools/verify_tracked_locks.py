from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_plane.cursor_projection import build_projection_manifest_payload
from control_plane.policy_loader import (
    build_policy_fingerprint_lock_payload,
    compute_loader_manifest_hash,
    compute_policy_fingerprint_from_payload,
    load_canonical_policy_payload,
)

SCOPED_CANON_PATHS = {
    "docs/specs/CANONICAL_INSTALLATION_DIRECTIVE.md",
    "docs/specs/CANONICAL_DAILY_CROSS_SECTIONAL_EQUITY_ALPHA_SPEC.md",
}


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
    expected_projection_lock = build_projection_manifest_payload(PROJECT_ROOT)

    if bootstrap.get("policy_fingerprint") != expected_fingerprint:
        raise SystemExit("Bootstrap lock policy fingerprint mismatch")
    if bootstrap.get("loader_manifest_hash") != expected_manifest_hash:
        raise SystemExit("Bootstrap lock loader manifest hash mismatch")
    if bootstrap.get("policy_path") != "AGENTS.md":
        raise SystemExit("Bootstrap lock policy_path must remain AGENTS.md")
    if bootstrap.get("policy_path") in SCOPED_CANON_PATHS:
        raise SystemExit("Bootstrap lock cannot promote a scoped canon doc to policy_path")
    if policy != expected_policy_lock:
        raise SystemExit("Policy fingerprint lock mismatch")
    if policy.get("policy_path") != "AGENTS.md":
        raise SystemExit("Policy fingerprint lock policy_path must remain AGENTS.md")
    if policy.get("policy_path") in SCOPED_CANON_PATHS:
        raise SystemExit("Policy fingerprint lock cannot promote a scoped canon doc to policy_path")
    if projection != expected_projection_lock:
        raise SystemExit("Projection lock mismatch")
    render_inputs = projection.get("render_inputs")
    if not isinstance(render_inputs, list) or not all(isinstance(item, str) for item in render_inputs):
        raise SystemExit("Projection lock render_inputs must be a list of strings")
    if any(item in SCOPED_CANON_PATHS for item in render_inputs):
        raise SystemExit("Projection lock cannot promote a scoped canon doc into render_inputs")

    print("tracked_locks_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
