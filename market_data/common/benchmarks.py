from __future__ import annotations

from dataclasses import dataclass

from market_data.common.settings import IngestionSettings, load_yaml_config


def derive_benchmark_id(symbol: str) -> str:
    """Stable benchmark_definitions.benchmark_id (not an instrument_id)."""
    normalized = symbol.lstrip("^").replace(".", "_")
    return f"bm_{normalized}"


@dataclass(frozen=True)
class BenchmarkDef:
    benchmark_id: str
    group: str
    symbol: str
    benchmark_type: str
    semantic_role: str
    default_usage: str
    proxy_for: str | None
    canonical_or_proxy: str


def load_benchmark_defs(settings: IngestionSettings) -> list[BenchmarkDef]:
    cfg = load_yaml_config("benchmarks.yaml", settings)
    out: list[BenchmarkDef] = []
    for group, entries in cfg.get("benchmarks", {}).items():
        for entry in entries or []:
            symbol = str(entry["symbol"])
            benchmark_id = str(entry["benchmark_id"]) if entry.get("benchmark_id") else derive_benchmark_id(symbol)
            out.append(
                BenchmarkDef(
                    benchmark_id=benchmark_id,
                    group=group,
                    symbol=symbol,
                    benchmark_type=str(entry["benchmark_type"]),
                    semantic_role=str(entry["semantic_role"]),
                    default_usage=str(entry["default_usage"]),
                    proxy_for=entry.get("proxy_for"),
                    canonical_or_proxy=str(entry["canonical_or_proxy"]),
                )
            )
    return out


def benchmark_symbols(settings: IngestionSettings) -> list[str]:
    return [b.symbol for b in load_benchmark_defs(settings)]
