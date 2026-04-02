from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from market_data.common.io_parquet import write_parquet
from market_data.common.paths import silver_path
from tools.verify_market_data_pit import run_checks

pytestmark = pytest.mark.ingestion

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_pit_verifier_fails_when_required_macro_tables_are_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="missing required PIT tables"):
        run_checks(
            data_lake=str(tmp_path),
            config_dir=str(_CONFIG_DIR),
        )


def test_pit_verifier_passes_with_contract_valid_macro_tables(
    test_settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vintage_dir = silver_path("macro_observations_vintage", test_settings)
    vintage_dir.mkdir(parents=True, exist_ok=True)
    vintages = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "vintage_date": [date(2024, 1, 10)],
            "release_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "available_from_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "available_to_ts_utc": [None],
            "source": ["fred"],
            "ingested_at_utc": [_utc(2024, 1, 10, 13, 1)],
        }
    ).with_columns(
        pl.col("release_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("available_to_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("ingested_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(vintages, vintage_dir / "vintages.parquet")

    asof_dir = silver_path("macro_asof_daily", test_settings)
    asof_dir.mkdir(parents=True, exist_ok=True)
    asof = pl.DataFrame(
        {
            "series_id": ["CPIAUCSL"],
            "asof_date": [date(2024, 1, 10)],
            "observation_date": [date(2024, 1, 1)],
            "value": [100.0],
            "selected_vintage_date": [date(2024, 1, 10)],
            "selected_available_from_ts_utc": [_utc(2024, 1, 10, 13, 0)],
            "selection_rule_version": ["macro_asof_latest_available_v1"],
            "built_at_utc": [_utc(2024, 1, 10, 13, 5)],
        }
    ).with_columns(
        pl.col("selected_available_from_ts_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("built_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    write_parquet(asof, asof_dir / "asof.parquet")

    assert (
        run_checks(
            data_lake=str(test_settings.data_lake_root),
            config_dir=str(test_settings.configs_dir),
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "[pit] macro QA warnings=0" in out
