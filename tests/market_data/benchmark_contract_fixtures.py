"""Minimal valid `benchmark_definitions` frames for contract tests."""

from __future__ import annotations

import polars as pl

from market_data.common.benchmarks import derive_benchmark_id

_CANONICAL_SECTOR_ETFS = (
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
    "XLRE",
    "XLC",
)


def minimal_valid_benchmark_definitions_pl() -> pl.DataFrame:
    """Satisfies sector-layer, SPY primary, and ^VIX / VIXY context validators."""
    rows: list[dict[str, object]] = []
    for sym in _CANONICAL_SECTOR_ETFS:
        rows.append(
            {
                "benchmark_id": derive_benchmark_id(sym),
                "group": "sectors",
                "symbol": sym,
                "benchmark_type": "sector",
                "semantic_role": f"sector-relative benchmark {sym}",
                "default_usage": "sector_relative_if_mapped",
                "proxy_for": f"{sym.lower()}_sector",
                "canonical_or_proxy": "proxy",
            }
        )
    rows.extend(
        [
            {
                "benchmark_id": derive_benchmark_id("SPY"),
                "group": "broad_market",
                "symbol": "SPY",
                "benchmark_type": "market",
                "semantic_role": "default broad market benchmark",
                "default_usage": "default_market_benchmark",
                "proxy_for": None,
                "canonical_or_proxy": "canonical",
            },
            {
                "benchmark_id": derive_benchmark_id("^VIX"),
                "group": "volatility",
                "symbol": "^VIX",
                "benchmark_type": "volatility_index",
                "semantic_role": "canonical spot-volatility index reference",
                "default_usage": "volatility_context",
                "proxy_for": None,
                "canonical_or_proxy": "canonical",
            },
            {
                "benchmark_id": derive_benchmark_id("VIXY"),
                "group": "volatility",
                "symbol": "VIXY",
                "benchmark_type": "volatility_etp",
                "semantic_role": "tradable volatility ETP proxy",
                "default_usage": "tradable_vol_proxy",
                "proxy_for": "^VIX",
                "canonical_or_proxy": "proxy",
            },
        ]
    )
    return pl.DataFrame(rows)
