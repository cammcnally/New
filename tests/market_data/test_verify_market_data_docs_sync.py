from __future__ import annotations

import pytest

from tools.verify_market_data_docs_sync import run_checks

pytestmark = pytest.mark.ingestion


def test_docs_sync_fails_without_required_docs() -> None:
    with pytest.raises(SystemExit, match="Missing docs"):
        run_checks(files=["market_data/silver/build_prices_1d_unadjusted.py"])


def test_docs_sync_passes_when_required_docs_change_too() -> None:
    assert (
        run_checks(
            files=[
                "market_data/silver/build_prices_1d_unadjusted.py",
                "README.md",
                "docs/data_contract.md",
                "market_data/COMMANDS.md",
            ]
        )
        == 0
    )


def test_docs_sync_fails_for_invalid_git_base_ref() -> None:
    with pytest.raises(SystemExit, match="git command failed"):
        run_checks(base_ref="definitely-not-a-ref")


@pytest.mark.parametrize("changed_file", ["Pipeline.py", "tools/run_repo_e2e.py"])
def test_docs_sync_treats_pipeline_and_e2e_runner_as_material(changed_file: str) -> None:
    with pytest.raises(SystemExit, match="Missing docs"):
        run_checks(files=[changed_file])
