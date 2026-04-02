"""Compatibility shim for `security_master`.

The canonical identity path is:

`instrument_master` -> `instrument_symbol_history` -> generated `security_master`

This module keeps the old import path operational while delegating generation to
`market_data.silver.compat_security_master`.
"""
from __future__ import annotations

from market_data.common.logging import get_logger
from market_data.common.settings import IngestionSettings

log = get_logger("silver.security_master")


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)
    from market_data.silver.compat_security_master import build as build_compat_security_master

    log.info("delegating legacy security_master build to canonical compatibility generator")
    return build_compat_security_master(settings=settings)
