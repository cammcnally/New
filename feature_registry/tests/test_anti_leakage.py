from __future__ import annotations

from pathlib import Path

import pytest

from feature_registry.definitions import PITSafety
from feature_registry.registry import FeatureRegistry


@pytest.fixture
def registry() -> FeatureRegistry:
    yml = Path(__file__).resolve().parent.parent / "features.yml"
    return FeatureRegistry.from_yaml(yml)


def test_registry_all_features_classified(registry: FeatureRegistry) -> None:
    for d in registry.to_dataframe().itertuples(index=False):
        assert d.pit_safety != PITSafety.UNKNOWN.value
        assert d.pit_safety in (
            PITSafety.SAFE.value,
            PITSafety.UNSAFE.value,
        )


def test_no_unsafe_in_default_set(registry: FeatureRegistry) -> None:
    for row in registry.to_dataframe().itertuples(index=False):
        if row.enabled_by_default:
            assert row.pit_safety != PITSafety.UNSAFE.value, (
                f"{row.name} is UNSAFE but enabled_by_default=True"
            )
