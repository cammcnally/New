from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PITSafety(str, Enum):
    """Point-in-time safety: whether the feature uses only information available at bar close."""

    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FeatureDef:
    name: str
    description: str
    entity: str = "ticker"
    timestamp_field: str = "timestamp_utc"
    family: str = ""
    pit_safety: PITSafety = PITSafety.SAFE
    owner: str = "pipeline"
    lookback_bars: Optional[int] = None
    enabled_by_default: bool = True
