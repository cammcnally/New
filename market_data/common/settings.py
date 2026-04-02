from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parents[2]


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    alpha_vantage_api_key: str = Field(alias="ALPHA_VANTAGE_API_KEY")
    fred_api_key: str = Field(alias="FRED_API_KEY")
    sec_user_agent: str = Field(alias="SEC_USER_AGENT")

    data_lake_root: Path = Field(default=_REPO_ROOT / "data_lake")
    configs_dir: Path = Field(default=_REPO_ROOT / "configs")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    av_requests_per_minute: int = 5
    av_requests_per_day: int = 25
    fred_requests_per_minute: int = 120
    sec_requests_per_second: float = 10.0


_cached: Optional[IngestionSettings] = None


def get_settings(**overrides: object) -> IngestionSettings:
    global _cached
    if overrides or _cached is None:
        _cached = IngestionSettings(**overrides)  # type: ignore[arg-type]
    return _cached


def load_yaml_config(name: str, settings: Optional[IngestionSettings] = None) -> dict:
    s = settings or get_settings()
    path = s.configs_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)
