from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import audit_file_registry as audit_module
from tools import report_cleanup_candidates as report_module


def test_audit_file_registry_passes_when_tracked_files_are_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "repo_control" / "file_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        """
schema_version: 1
entries:
  - path: README.md
    class: normative_doc
    authority: authoritative
    owner_layer: docs
    cleanup_policy: keep
    regeneration_source: ""
    review_required: false
    reason: readme
    last_reviewed: "2026-04-02"
  - path: src/**
    class: canonical
    authority: authoritative
    owner_layer: tooling
    cleanup_policy: keep
    regeneration_source: ""
    review_required: false
    reason: src
    last_reviewed: "2026-04-02"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(audit_module, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(audit_module, "_git_lines", lambda *args: ["README.md", "src/app.py"])

    assert audit_module.main() == 0


def test_report_cleanup_candidates_writes_expected_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "repo_control" / "file_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        """
schema_version: 1
entries:
  - path: README.md
    class: normative_doc
    authority: authoritative
    owner_layer: docs
    cleanup_policy: keep
    regeneration_source: ""
    review_required: false
    reason: readme
    last_reviewed: "2026-04-02"
  - path: legacy/**
    class: compatibility_only
    authority: compatibility
    owner_layer: tooling
    cleanup_policy: review_first
    regeneration_source: ""
    review_required: true
    reason: legacy bridge
    last_reviewed: "2026-04-02"
  - path: outputs/**
    class: ignore_runtime_output
    authority: local_only
    owner_layer: local_runtime
    cleanup_policy: delete_on_sight
    regeneration_source: ""
    review_required: false
    reason: runtime outputs
    last_reviewed: "2026-04-02"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("see legacy/adapter.py", encoding="utf-8")
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "adapter.py").write_text("legacy adapter", encoding="utf-8")

    output_path = tmp_path / "outputs" / "repo_cleanup_report.json"
    monkeypatch.setattr(report_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(report_module, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(report_module, "DEFAULT_OUTPUT_PATH", output_path)
    monkeypatch.setattr(
        report_module,
        "_git_lines",
        lambda *args: ["README.md", "legacy/adapter.py"] if args == ("ls-files",) else ["outputs/temp.json"],
    )

    assert report_module.main([]) == 0

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["unregistered_tracked_files"] == []
    assert report["delete_candidates"][0]["path"] == "outputs/temp.json"
    assert report["files_requiring_human_review"][0]["path"] == "legacy/adapter.py"
