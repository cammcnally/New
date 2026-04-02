from __future__ import annotations

from pathlib import Path

import pytest

from market_data.common.hashing import hash_file
from market_data.common.manifest import (
    build_export_manifest,
    stable_content_id,
    get_git_commit,
)

pytestmark = pytest.mark.ingestion


def test_stable_content_id_uses_hash_prefix() -> None:
    assert stable_content_id("export-panel", "abcdef1234567890fedcba") == "export-panel-abcdef1234567890"


def test_build_export_manifest_uses_stable_export_id(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.csv"
    panel_path.write_text(
        "ticker,timestamp_utc,open,high,low,close,volume,is_incomplete_session\n"
        "AAA,2024-01-08T21:00:00Z,10,11,9,10.5,1000,false\n",
        encoding="utf-8",
    )

    expected_hash = hash_file(panel_path)
    manifest = build_export_manifest(
        output_path=panel_path,
        contract_name="export_panel",
        start_date="2024-01-01",
        end_date="2024-01-10",
        row_count=1,
        ticker_count=1,
        dataset_build_id="dataset-build-1",
        verification_artifacts=[{"name": "contracts", "path": "data_lake/manifests/verification_summary.json"}],
        deferred_components=["instrument_classification_history"],
    )

    assert manifest["dataset_build_id"] == "dataset-build-1"
    assert manifest["content_hash"] == expected_hash
    assert manifest["export_panel_version_id"] == stable_content_id("export-panel", expected_hash)
    assert manifest["generated_at_utc"] != manifest["export_panel_version_id"]
    assert manifest["start_date"] == "2024-01-01"
    assert manifest["end_date"] == "2024-01-10"
    assert manifest["verification_artifacts"] == [{"name": "contracts", "path": "data_lake/manifests/verification_summary.json"}]
    assert manifest["deferred_components"] == ["instrument_classification_history"]


def test_build_export_manifest_requires_dataset_build_id(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.csv"
    panel_path.write_text(
        "ticker,timestamp_utc,open,high,low,close,volume,is_incomplete_session\n"
        "AAA,2024-01-08T21:00:00Z,10,11,9,10.5,1000,false\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dataset_build_id is required"):
        build_export_manifest(
            output_path=panel_path,
            contract_name="export_panel",
            start_date="2024-01-01",
            end_date="2024-01-10",
            row_count=1,
            ticker_count=1,
            dataset_build_id=None,
        )


def test_get_git_commit_falls_back_to_ci_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("git unavailable")

    monkeypatch.setattr("market_data.common.manifest.subprocess.run", _raise)
    monkeypatch.setenv("GITHUB_SHA", "abc123ci")

    assert get_git_commit() == "abc123ci"
