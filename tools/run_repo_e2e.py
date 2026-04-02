from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_data.common.settings import get_settings
from market_data.orchestration.e2e import STAGES, run_e2e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the authoritative local repo e2e pipeline.")
    parser.add_argument("--data-lake", default=None, help="Override market data lake root")
    parser.add_argument("--config-dir", default=None, help="Override market data config dir")
    parser.add_argument("--bootstrap-start-date", default="2010-01-01", help="Bootstrap start date when no watermark exists")
    parser.add_argument("--panel-path", default="panel_ohlcv_clean.csv", help="Exported panel output path")
    parser.add_argument("--pipeline-output-dir", default="pipeline_outputs", help="Pipeline.py output directory")
    parser.add_argument("--resume", action="store_true", help="Resume after the last successful e2e stage")
    parser.add_argument("--from-stage", choices=STAGES, default=None, help="Restart from a specific e2e stage")
    parser.add_argument("--stop-after", choices=STAGES, default=None, help="Stop after a specific e2e stage")
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {}
    if args.data_lake:
        overrides["data_lake_root"] = Path(args.data_lake).resolve()
    if args.config_dir:
        overrides["configs_dir"] = Path(args.config_dir).resolve()
    settings = get_settings(**overrides)

    run_e2e(
        settings=settings,
        bootstrap_start_date=args.bootstrap_start_date,
        panel_path=args.panel_path,
        pipeline_output_dir=args.pipeline_output_dir,
        resume=args.resume,
        from_stage=args.from_stage,
        stop_after=args.stop_after,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
