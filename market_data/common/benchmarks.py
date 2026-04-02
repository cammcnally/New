from __future__ import annotations

from dataclasses import dataclass

from market_data.common.settings import IngestionSettings, load_yaml_config


@dataclass(frozen=True)
class BenchmarkDef:
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
            out.append(
                BenchmarkDef(
                    group=group,
                    symbol=str(entry["symbol"]),
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
