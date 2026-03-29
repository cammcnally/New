from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, cast

import pandas as pd
import yaml  # type: ignore[import-untyped]

from .definitions import FeatureDef, PITSafety


def _parse_pit_safety(raw: object) -> PITSafety:
    if isinstance(raw, PITSafety):
        return raw
    if raw is None:
        return PITSafety.UNKNOWN
    s = str(raw).strip().upper()
    try:
        return PITSafety[s]
    except KeyError:
        return PITSafety.UNKNOWN


def _coerce_lookback_bars(raw: object) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise TypeError("lookback_bars must be int or null, not bool")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    raise TypeError(f"lookback_bars must be int or null, got {type(raw).__name__}")


def _feature_def_from_mapping(m: Dict[str, object]) -> FeatureDef:
    return FeatureDef(
        name=str(m["name"]),
        description=str(m.get("description", "")),
        entity=str(m.get("entity", "ticker")),
        timestamp_field=str(m.get("timestamp_field", "timestamp_utc")),
        family=str(m.get("family", "")),
        pit_safety=_parse_pit_safety(m.get("pit_safety", "SAFE")),
        owner=str(m.get("owner", "pipeline")),
        lookback_bars=_coerce_lookback_bars(m.get("lookback_bars")),
        enabled_by_default=bool(m.get("enabled_by_default", True)),
    )


class FeatureRegistry:
    def __init__(self, definitions: List[FeatureDef]) -> None:
        self._defs: Dict[str, FeatureDef] = {d.name: d for d in definitions}

    @classmethod
    def from_yaml(cls, path: Path) -> "FeatureRegistry":
        data = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
        if not data:
            return cls([])
        items = data.get("features", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("YAML root must be a list or contain a 'features' list")
        defs = [_feature_def_from_mapping(dict(x)) for x in items]
        names = [d.name for d in defs]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"Duplicate feature names in registry: {dupes}")
        return cls(defs)

    def get(self, name: str) -> FeatureDef:
        return self._defs[name]

    def list_by_family(self, family: str) -> List[FeatureDef]:
        return [d for d in self._defs.values() if d.family == family]

    def list_pit_safe(self) -> List[FeatureDef]:
        return [d for d in self._defs.values() if d.pit_safety == PITSafety.SAFE]

    def validate_no_leakage(self, feature_names: List[str]) -> List[str]:
        unsafe: List[str] = []
        for n in feature_names:
            d = self._defs.get(n)
            if d is not None and d.pit_safety == PITSafety.UNSAFE:
                unsafe.append(n)
        return unsafe

    def to_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "name": d.name,
                "description": d.description,
                "entity": d.entity,
                "timestamp_field": d.timestamp_field,
                "family": d.family,
                "pit_safety": d.pit_safety.value,
                "owner": d.owner,
                "lookback_bars": d.lookback_bars,
                "enabled_by_default": d.enabled_by_default,
            }
            for d in sorted(self._defs.values(), key=lambda x: x.name)
        ]
        return pd.DataFrame(rows)
