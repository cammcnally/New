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


def refresh_bootstrap_locks(project_root: Path | None = None) -> tuple[Path, Path]:
    root = (project_root or PROJECT_ROOT).resolve()
    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        raise SystemExit("Missing AGENTS.md")
    payload = load_canonical_policy_payload(agents_path)
    policy_fingerprint = compute_policy_fingerprint_from_payload(payload)
    loader_manifest_hash = compute_loader_manifest_hash(root)
    contracts_root = root / "contracts"
    contracts_root.mkdir(parents=True, exist_ok=True)

    bootstrap_lock = contracts_root / "bootstrap_pin.lock.json"
    policy_lock = contracts_root / "policy_fingerprint.lock.json"

    bootstrap_lock.write_text(
        json.dumps(
            {
                "policy_path": "AGENTS.md",
                "policy_fingerprint": policy_fingerprint,
                "loader_manifest_path": "control_plane/loader_manifest.json",
                "loader_manifest_hash": loader_manifest_hash,
                "policy_version": payload.get("policy_version"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    policy_lock.write_text(
        json.dumps(build_policy_fingerprint_lock_payload(root, payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bootstrap_lock, policy_lock


def main() -> int:
    bootstrap_lock, policy_lock = refresh_bootstrap_locks()
    print(f"wrote {bootstrap_lock}")
    print(f"wrote {policy_lock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
