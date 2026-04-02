from __future__ import annotations

from typing import TypedDict


class AlphaDiagnosticsManifest(TypedDict, total=False):
    strategy_name: str
    run_id: str
    return_basis: str
    alphalens_version: str
    quantiles: int
    periods: list[int]
    artifacts: list[str]
