from __future__ import annotations

import pytest

import market_data.common.settings as settings_mod
from market_data.common.settings import IngestionSettings, load_yaml_config

pytestmark = pytest.mark.ingestion


def test_settings_load(monkeypatch: pytest.MonkeyPatch, tmp_lake, test_settings: IngestionSettings) -> None:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "env_alpha")
    monkeypatch.setenv("FRED_API_KEY", "env_fred")
    monkeypatch.setenv("SEC_USER_AGENT", "Env Agent env@example.com")
    settings_mod._cached = None
    s = IngestionSettings(
        data_lake_root=tmp_lake,
        configs_dir=test_settings.configs_dir,
    )
    assert s.alpha_vantage_api_key == "env_alpha"
    assert s.fred_api_key == "env_fred"
    assert s.sec_user_agent == "Env Agent env@example.com"


def test_load_yaml_config(test_settings: IngestionSettings) -> None:
    cfg = load_yaml_config("macro_series.yaml", settings=test_settings)
    assert "series" in cfg
    assert isinstance(cfg["series"], list)
    assert cfg["series"][0]["id"] == "DFF"
