from __future__ import annotations

import os
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_data.common.settings import IngestionSettings


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def add_market_data_args(parser: ArgumentParser) -> None:
    parser.add_argument("--data-lake", default=None, help="Override market data lake root")
    parser.add_argument("--config-dir", default=None, help="Override market data config dir")


def load_verification_settings(args: Namespace) -> IngestionSettings:
    overrides: dict[str, object] = {
        "alpha_vantage_api_key": os.getenv("ALPHA_VANTAGE_API_KEY", "verification"),
        "fred_api_key": os.getenv("FRED_API_KEY", "verification"),
        "sec_user_agent": os.getenv(
            "SEC_USER_AGENT",
            "Market Data Verification verification@example.com",
        ),
    }
    if getattr(args, "data_lake", None):
        overrides["data_lake_root"] = Path(args.data_lake).resolve()
    if getattr(args, "config_dir", None):
        overrides["configs_dir"] = Path(args.config_dir).resolve()
    return IngestionSettings(**overrides)
