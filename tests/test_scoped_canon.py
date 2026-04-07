from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from tools.verify_scoped_canon import (
    COMMON_HIGHER_AUTHORITIES,
    DIRECTIVE_RELATIVE,
    EXPECTED_LOWER_DOC_REFERENCES,
    EXPECTED_MARKDOWN_SNIPPETS,
    LOWER_PRECEDENCE_DOCS,
    MIRROR_SPECS,
    TARGET_SPEC_RELATIVE,
    run_checks,
)

pytestmark = pytest.mark.regression


def _write_text(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_scoped_canon_fixture(root: Path) -> None:
    for relative_path, snippets in EXPECTED_MARKDOWN_SNIPPETS.items():
        _write_text(root, relative_path, "# Fixture\n\n" + "\n".join(snippets) + "\n")

    for relative_path, snippets in EXPECTED_LOWER_DOC_REFERENCES.items():
        _write_text(root, relative_path, "# Fixture\n\n" + "\n".join(snippets) + "\n")

    for mirror_id, spec in MIRROR_SPECS.items():
        payload = {
            "schema_version": 1,
            "mirror_id": mirror_id,
            "scoped_canon_source": DIRECTIVE_RELATIVE,
            "area_status": "mixed_current_and_deferred",
            "precedence": {
                "higher_priority_authorities": COMMON_HIGHER_AUTHORITIES,
                "preserved_runtime_surface": "Pipeline.py",
                "lower_precedence_surfaces": LOWER_PRECEDENCE_DOCS,
            },
            "effective_current_canon": {
                "authority": spec["current_authority_includes"],
                "summary": "fixture current state",
                "implemented_state": dict(spec["current_state"]),
            },
            "deferred_target_canon": {
                "authority": spec["deferred_authority"],
                "summary": "fixture deferred state",
                "target_state": dict(spec["deferred_state"]),
            },
        }
        _write_text(root, f"config/canonical/{mirror_id}.yaml", yaml.safe_dump(payload, sort_keys=False))


def test_scoped_canon_verifier_accepts_valid_fixture(tmp_path: Path) -> None:
    _write_scoped_canon_fixture(tmp_path)
    assert run_checks(tmp_path) == 0


def test_scoped_canon_verifier_rejects_active_poetry_runtime(tmp_path: Path) -> None:
    _write_scoped_canon_fixture(tmp_path)
    runtime_path = tmp_path / "config" / "canonical" / "runtime.yaml"
    payload = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    payload["effective_current_canon"]["implemented_state"]["package_manager"] = "Poetry"
    runtime_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(SystemExit, match="runtime.yaml current state mismatch for package_manager"):
        run_checks(tmp_path)


def test_scoped_canon_verifier_requires_lower_doc_references(tmp_path: Path) -> None:
    _write_scoped_canon_fixture(tmp_path)
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Fixture\n\n" + TARGET_SPEC_RELATIVE + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="README.md missing required snippets"):
        run_checks(tmp_path)
