from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_pass_contract import collect_policy_errors


PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.regression


def test_pass_contract_policy_wiring_passes_for_repo_state() -> None:
    assert collect_policy_errors(PROJECT_ROOT) == []
