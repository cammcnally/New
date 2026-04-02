from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from tools.verify_market_data_bridge import run_checks as run_bridge_checks
    from tools.verify_market_data_contracts import run_checks as run_contract_checks
    from tools.verify_market_data_docs_sync import run_checks as run_docs_sync_checks
    from tools.verify_market_data_pit import run_checks as run_pit_checks
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_bridge import run_checks as run_bridge_checks
    from verify_market_data_contracts import run_checks as run_contract_checks
    from verify_market_data_docs_sync import run_checks as run_docs_sync_checks
    from verify_market_data_pit import run_checks as run_pit_checks

_COMPAT_GUARD_TESTS = [
    "tests/market_data/test_identity_orchestration.py",
    "tests/market_data/test_identity_cutover.py",
]


def run_compat_guard() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *_COMPAT_GUARD_TESTS, "-q"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "[compat] canonical identity compatibility guard failed.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def run_checks(
    *,
    data_lake: str | None = None,
    config_dir: str | None = None,
    panel_path: str = "panel_ohlcv_clean.csv",
    base_ref: str | None = None,
    files: list[str] | None = None,
) -> dict[str, Any]:
    files = files or []
    results: dict[str, Any] = {}
    run_docs_sync_checks(base_ref=base_ref, files=files)
    results["docs_sync_guard"] = "passed"
    run_contract_checks(data_lake=data_lake, config_dir=config_dir)
    results["schema_guard"] = "passed"
    run_pit_checks(data_lake=data_lake, config_dir=config_dir)
    results["pit_guard"] = "passed"
    run_compat_guard()
    results["compat_guard"] = "passed"
    run_bridge_checks(
        panel_path=panel_path,
        require_manifest=True,
        data_lake=data_lake,
        config_dir=config_dir,
    )
    results["bridge_guard"] = "passed"
    results["verification_guard"] = "passed"
    print("[verify-market-data] all checks completed")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run market-data verification bundle.")
    parser.add_argument("--data-lake", default=None, help="Override market data lake root")
    parser.add_argument("--config-dir", default=None, help="Override market data config dir")
    parser.add_argument("--panel-path", default="panel_ohlcv_clean.csv", help="Exported panel path")
    parser.add_argument("--base-ref", default=None, help="Base git ref for docs-sync verification")
    parser.add_argument("--file", dest="files", action="append", default=[], help="Explicit changed file path")
    args = parser.parse_args(argv)
    run_checks(
        data_lake=args.data_lake,
        config_dir=args.config_dir,
        panel_path=args.panel_path,
        base_ref=args.base_ref,
        files=args.files,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
