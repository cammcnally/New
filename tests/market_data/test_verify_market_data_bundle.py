from __future__ import annotations

import pytest

from tools import verify_market_data as bundle_module

pytestmark = pytest.mark.ingestion


def test_verify_market_data_bundle_records_all_guard_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bundle_module, "run_docs_sync_checks", lambda **_: None)
    monkeypatch.setattr(bundle_module, "run_contract_checks", lambda **_: None)
    monkeypatch.setattr(bundle_module, "run_pit_checks", lambda **_: None)
    monkeypatch.setattr(bundle_module, "run_compat_guard", lambda: None)
    monkeypatch.setattr(bundle_module, "run_bridge_checks", lambda **_: None)

    results = bundle_module.run_checks(
        data_lake="E:/fake-lake",
        config_dir="E:/fake-configs",
        panel_path="panel.csv",
        base_ref="origin/main",
        files=["README.md"],
    )

    assert results == {
        "docs_sync_guard": "passed",
        "schema_guard": "passed",
        "pit_guard": "passed",
        "compat_guard": "passed",
        "bridge_guard": "passed",
        "verification_guard": "passed",
    }
