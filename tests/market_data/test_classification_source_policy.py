from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from market_data.common.classification import (
    build_effective_windows,
    load_classification_source_policy,
    validate_non_overlapping_windows,
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


def test_load_classification_source_policy_reads_repo_policy(test_settings) -> None:
    policy = load_classification_source_policy(test_settings)
    assert policy.source_name == "SEC_EDGAR_XBRL"
    assert policy.classification_system == "SEC_SIC_4"
    assert policy.field_precedence == ("dei:EntityPrimarySicNumber", "filing_header_sic")
    assert policy.missing_policy == "keep_missing"


def test_load_classification_source_policy_rejects_invalid_enum(tmp_path: Path, tmp_lake: Path) -> None:
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "classification_sources.yaml").write_text(
        "classification_sources:\n"
        "  primary:\n"
        "    source_name: SEC_EDGAR_XBRL\n"
        "    classification_system: gics\n"
        "    field_precedence: ['dei:EntityPrimarySicNumber', 'filing_header_sic']\n"
        "    missing_policy: keep_missing\n",
        encoding="utf-8",
    )
    settings = _settings_with_config_dir(cfg, tmp_lake)
    with pytest.raises(ValueError, match="SEC_SIC_4"):
        load_classification_source_policy(settings)


def test_build_effective_windows_creates_deterministic_ranges() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1, 1],
            "classification_system": ["SEC_SIC_4", "SEC_SIC_4"],
            "effective_from": [date(2024, 1, 1), date(2024, 2, 1)],
            "sector_code": ["1311", "1311"],
            "sector_name": ["Energy", "Energy"],
            "source": ["sec_edgar", "sec_edgar"],
            "asof_timestamp": [
                datetime(2024, 1, 5, tzinfo=timezone.utc),
                datetime(2024, 2, 5, tzinfo=timezone.utc),
            ],
        }
    ).with_columns(pl.col("asof_timestamp").cast(pl.Datetime("us", "UTC")))
    out = build_effective_windows(df)
    assert out["effective_to"].to_list() == [date(2024, 1, 31), None]
    validate_non_overlapping_windows(out)


def test_validate_non_overlapping_windows_rejects_overlap() -> None:
    df = pl.DataFrame(
        {
            "instrument_id": [1, 1],
            "classification_system": ["SEC_SIC_4", "SEC_SIC_4"],
            "effective_from": [date(2024, 1, 1), date(2024, 1, 15)],
            "effective_to": [date(2024, 1, 31), None],
        }
    ).with_columns(pl.col("effective_to").cast(pl.Date))
    with pytest.raises(ValueError, match="overlap"):
        validate_non_overlapping_windows(df)
