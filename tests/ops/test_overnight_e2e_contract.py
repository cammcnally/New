from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_e2e_contract_json_parseable() -> None:
    path = _REPO_ROOT / "ops" / "overnight" / "e2e_contract.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("contract_id")
    assert data.get("dev_green_required_stages")


def test_check_e2e_contract_contract_info_exits_zero() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "ops" / "overnight" / "check_e2e_contract.py"), "--mode", "contract-info"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout.strip())
    assert out["contract_id"] == "DEV_EXPORT_SPINE_GREEN"
