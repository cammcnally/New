from __future__ import annotations

from pathlib import Path

import pytest

from market_data.common.classification import (
    load_sec_sic_crosswalk,
    normalize_sic_code,
    resolve_sector_etf_from_sic,
)
from market_data.common.settings import IngestionSettings

pytestmark = pytest.mark.ingestion


def _settings_with_config_dir(configs_dir: Path, tmp_lake: Path) -> IngestionSettings:
    return IngestionSettings(  # type: ignore[call-arg]
        data_lake_root=tmp_lake,
        configs_dir=configs_dir,
        alpha_vantage_api_key="test_key",
        fred_api_key="test_key",
        sec_user_agent="Test Agent test@test.com",
    )


def test_normalize_sic_code_handles_common_inputs() -> None:
    assert normalize_sic_code(" 1311 ") == "1311"
    assert normalize_sic_code(1311) == "1311"
    assert normalize_sic_code("13110") == "1311"
    assert normalize_sic_code(None) is None
    assert normalize_sic_code("abc") is None


def test_load_sec_sic_crosswalk_reads_repo_crosswalk(test_settings) -> None:
    crosswalk = load_sec_sic_crosswalk(test_settings)
    assert crosswalk.classification_system == "SEC_SIC_4"
    assert crosswalk.mapping_rule_version == "sec_sic4_to_sector_etf_v1"
    assert resolve_sector_etf_from_sic("1311", crosswalk) == "XLE"
    assert resolve_sector_etf_from_sic("3571", crosswalk) == "XLK"
    assert resolve_sector_etf_from_sic("9999", crosswalk) is None


def test_load_sec_sic_crosswalk_rejects_duplicate_mapping(tmp_path: Path, tmp_lake: Path) -> None:
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "sec_sic4_to_sector_etf.yaml").write_text(
        "sec_sic4_to_sector_etf:\n"
        "  mapping_rule_version: sec_sic4_to_sector_etf_v1\n"
        "  classification_system: SEC_SIC_4\n"
        "  mappings:\n"
        "    - source_prefix: '13'\n"
        "      sector_etf: XLE\n"
        "      sector_name: Energy\n"
        "    - source_prefix: '13'\n"
        "      sector_etf: XLF\n"
        "      sector_name: Financials\n",
        encoding="utf-8",
    )
    settings = _settings_with_config_dir(cfg, tmp_lake)
    with pytest.raises(ValueError, match="duplicate"):
        load_sec_sic_crosswalk(settings)


def test_load_sec_sic_crosswalk_rejects_invalid_target_sector(tmp_path: Path, tmp_lake: Path) -> None:
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "sec_sic4_to_sector_etf.yaml").write_text(
        "sec_sic4_to_sector_etf:\n"
        "  mapping_rule_version: sec_sic4_to_sector_etf_v1\n"
        "  classification_system: SEC_SIC_4\n"
        "  mappings:\n"
        "    - source_prefix: '13'\n"
        "      sector_etf: SPY\n"
        "      sector_name: NotAllowed\n",
        encoding="utf-8",
    )
    settings = _settings_with_config_dir(cfg, tmp_lake)
    with pytest.raises(ValueError, match="invalid target"):
        load_sec_sic_crosswalk(settings)
