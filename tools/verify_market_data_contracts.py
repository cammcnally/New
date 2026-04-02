from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_data.common.io_parquet import read_parquet
from market_data.common.pandera_contracts import contract_status, validate_contract_df
from market_data.common.paths import silver_path

try:
    from tools.verify_market_data_common import add_market_data_args, load_verification_settings
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_common import add_market_data_args, load_verification_settings


CONTRACT_PATHS = {
    "instrument_master": "instrument_master",
    "instrument_symbol_history": "instrument_symbol_history",
    "benchmark_definitions": "benchmark_definitions",
    "trading_calendar": "trading_calendar",
    "prices_1d_unadjusted": "prices_1d_unadjusted",
    "macro_observations_vintage": "macro_observations_vintage",
    "macro_asof_daily": "macro_asof_daily",
    "instrument_classification_history": "instrument_classification_history",
    "instrument_benchmark_map": "instrument_benchmark_map",
}


def run_checks(*, data_lake: str | None = None, config_dir: str | None = None) -> int:
    args = argparse.Namespace(data_lake=data_lake, config_dir=config_dir)
    settings = load_verification_settings(args)

    checked = 0
    required_failures: list[str] = []
    skipped: list[str] = []
    for contract_name, dataset_name in CONTRACT_PATHS.items():
        status = contract_status(contract_name)
        required = status != "contract_defined_deferred"
        path = silver_path(dataset_name, settings)
        if not path.exists():
            if required:
                required_failures.append(f"{contract_name}: missing")
            else:
                skipped.append(f"{contract_name}: missing")
            continue
        try:
            df = read_parquet(path).collect()
        except Exception as exc:  # pragma: no cover - surfaced through exit status
            raise SystemExit(f"[contracts] failed to read {contract_name}: {exc}") from exc
        if df.is_empty():
            if required:
                required_failures.append(f"{contract_name}: empty")
            else:
                skipped.append(f"{contract_name}: empty")
            continue
        try:
            validate_contract_df(contract_name, df)
        except Exception as exc:  # pragma: no cover - surfaced through exit status
            raise SystemExit(f"[contracts] {contract_name} ({status}) failed: {exc}") from exc
        print(f"[contracts] {contract_name} ({status}): ok ({len(df)} rows)")
        checked += 1

    if required_failures:
        raise SystemExit(f"[contracts] missing required canonical tables: {required_failures}")
    print(f"[contracts] checked={checked} skipped={len(skipped)}")
    for item in skipped:
        print(f"[contracts] skip {item}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate available market-data tables against Pandera contracts.")
    add_market_data_args(parser)
    args = parser.parse_args(argv)
    return run_checks(data_lake=args.data_lake, config_dir=args.config_dir)


if __name__ == "__main__":
    raise SystemExit(main())
