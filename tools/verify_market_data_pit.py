from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_data.common.io_parquet import read_parquet
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.paths import silver_path
from market_data.qa.qa_macro import check as qa_macro_check

try:
    from tools.verify_market_data_common import add_market_data_args, load_verification_settings
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_common import add_market_data_args, load_verification_settings


def run_checks(*, data_lake: str | None = None, config_dir: str | None = None) -> int:
    args = argparse.Namespace(data_lake=data_lake, config_dir=config_dir)
    settings = load_verification_settings(args)

    macro_vintage_path = silver_path("macro_observations_vintage", settings)
    macro_asof_path = silver_path("macro_asof_daily", settings)
    required_failures: list[str] = []

    if macro_vintage_path.exists():
        vintages = read_parquet(macro_vintage_path).collect()
        if not vintages.is_empty():
            validate_contract_df("macro_observations_vintage", vintages)
            print(f"[pit] macro_observations_vintage: ok ({len(vintages)} rows)")
        else:
            required_failures.append("macro_observations_vintage: empty")
    else:
        required_failures.append("macro_observations_vintage: missing")

    if macro_asof_path.exists():
        asof = read_parquet(macro_asof_path).collect()
        if not asof.is_empty():
            validate_contract_df("macro_asof_daily", asof)
            print(f"[pit] macro_asof_daily: ok ({len(asof)} rows)")
        else:
            required_failures.append("macro_asof_daily: empty")
    else:
        required_failures.append("macro_asof_daily: missing")

    if required_failures:
        raise SystemExit(f"[pit] missing required PIT tables: {required_failures}")

    findings = qa_macro_check(settings=settings)
    if findings.get("errors"):
        raise SystemExit(f"[pit] macro QA errors: {findings['errors']}")
    print(f"[pit] macro QA warnings={len(findings.get('warnings', []))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify PIT-sensitive market-data surfaces.")
    add_market_data_args(parser)
    args = parser.parse_args(argv)
    return run_checks(data_lake=args.data_lake, config_dir=args.config_dir)


if __name__ == "__main__":
    raise SystemExit(main())
