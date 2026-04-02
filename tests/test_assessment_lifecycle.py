from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "control_plane" / "assessment_registry.json"
ACTIVE_REQUIRED_FIELDS = (
    "Assessment Type:",
    "Status:",
    "Assessed At:",
    "Assessed From Commit:",
    "Assessed From Branch:",
    "Scope:",
    "Supersedes:",
    "Superseded By:",
    "Authority Level:",
)


def _load_registry() -> dict[str, object]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_assessment_registry_has_exactly_one_active_record_per_type() -> None:
    registry = _load_registry()
    active_counts: dict[str, int] = {}
    for record in registry["records"]:
        if record["status"] == "ACTIVE":
            active_counts[record["assessment_type"]] = active_counts.get(record["assessment_type"], 0) + 1

    assert active_counts
    assert all(count == 1 for count in active_counts.values())


def test_active_assessment_docs_have_required_metadata_header() -> None:
    registry = _load_registry()
    active_paths = [ROOT / record["canonical_path"] for record in registry["records"] if record["status"] == "ACTIVE"]

    for path in active_paths:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# ")
        assert "\n# Assessment Metadata\n" in text
        for field in ACTIVE_REQUIRED_FIELDS:
            assert field in text


def test_superseded_assessment_docs_have_visible_banner() -> None:
    archive_paths = sorted((ROOT / "docs" / "archive" / "assessments").glob("**/*.md"))
    historical_paths = [p for p in archive_paths if p.exists()]

    for path in historical_paths:
        text = path.read_text(encoding="utf-8")
        top = "\n".join(text.splitlines()[:4])
        assert "> **SUPERSEDED**" in top
        assert "Current file:" in top


def test_registry_canonical_paths_exist() -> None:
    registry = _load_registry()

    for record in registry["records"]:
        assert (ROOT / record["canonical_path"]).exists()
