from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DIRECTIVE_RELATIVE = "docs/specs/CANONICAL_INSTALLATION_DIRECTIVE.md"
TARGET_SPEC_RELATIVE = "docs/specs/CANONICAL_DAILY_CROSS_SECTIONAL_EQUITY_ALPHA_SPEC.md"
CHANGE_CONTROL_RELATIVE = "docs/governance/CHANGE_CONTROL.md"
ACCEPTANCE_GATES_RELATIVE = "docs/governance/ACCEPTANCE_GATES.md"
LOWER_PRECEDENCE_DOCS = [
    "README.md",
    "docs/implementation_runbook.md",
    "market_data/COMMANDS.md",
    "docs/end_to_end_trading_system_architecture.md",
]
COMMON_HIGHER_AUTHORITIES = [
    "AGENTS.md",
    "docs/phase1-research-spec.md",
    "docs/phase1-execution-roadmap.md",
]
EXPECTED_MARKDOWN_SNIPPETS = {
    DIRECTIVE_RELATIVE: [
        "## Non-supersession Boundary",
        "AGENTS.md",
        "docs/phase1-research-spec.md",
        "docs/phase1-execution-roadmap.md",
        "Pipeline.py",
        "Poetry is deferred and not authoritative",
        "`config/canonical/` is a machine-readable mirror",
    ],
    TARGET_SPEC_RELATIVE: [
        "## Status And Authority Boundary",
        "It is not a claim that the current Phase 1 runtime has already been replaced.",
        "market_data/",
        "Pipeline.py",
    ],
    CHANGE_CONTROL_RELATIVE: [
        "## Precedence Order",
        "tools/verify_scoped_canon.py",
        "Do not try to smuggle",
    ],
    ACCEPTANCE_GATES_RELATIVE: [
        "## Required Commands",
        "tools/verify_scoped_canon.py",
        "Poetry is the active package-management authority",
    ],
}
EXPECTED_LOWER_DOC_REFERENCES = {
    "README.md": [
        DIRECTIVE_RELATIVE,
        TARGET_SPEC_RELATIVE,
        "config/canonical/",
        "tools/verify_scoped_canon.py",
    ],
    "docs/implementation_runbook.md": [
        DIRECTIVE_RELATIVE,
        "tools/verify_scoped_canon.py",
    ],
    "market_data/COMMANDS.md": [
        DIRECTIVE_RELATIVE,
        "tools/verify_scoped_canon.py",
    ],
    "docs/end_to_end_trading_system_architecture.md": [
        DIRECTIVE_RELATIVE,
        TARGET_SPEC_RELATIVE,
    ],
}
MIRROR_SPECS: dict[str, dict[str, Any]] = {
    "runtime": {
        "current_authority_includes": ["AGENTS.md"],
        "current_state": {
            "package_manager": "uv",
            "python_version": "3.11.9",
            "venv_path": ".venv",
        },
        "deferred_authority": [DIRECTIVE_RELATIVE],
        "deferred_state": {
            "package_manager": "Poetry",
            "status": "deferred_requires_separate_approval",
        },
    },
    "dependencies": {
        "current_authority_includes": ["AGENTS.md", "pyproject.toml", "uv.lock"],
        "current_state": {
            "package_manager": "uv",
            "authoritative_lockfile": "uv.lock",
        },
        "deferred_authority": [DIRECTIVE_RELATIVE],
        "deferred_state": {
            "poetry_cutover": "not_active",
            "status": "deferred_requires_protected_infrastructure_replacement",
        },
    },
    "data": {
        "current_authority_includes": ["README.md", "docs/data_contract.md"],
        "current_state": {
            "canonical_data_layer_root": "market_data/",
            "active_config_root": "configs/",
            "compatibility_consumer": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "preferred_modular_layout": "pipeline/",
            "status": "deferred_requires_migration",
        },
    },
    "features": {
        "current_authority_includes": ["docs/phase1-research-spec.md", "Pipeline.py", "feature_registry/"],
        "current_state": {
            "current_scope": "frozen_phase1_feature_validation_and_runtime",
            "runtime_surface": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "target_feature_stack": "returns_volatility_momentum_liquidity_rank_interactions",
            "status": "deferred_target_architecture_only",
        },
    },
    "models": {
        "current_authority_includes": ["docs/phase1-research-spec.md", "Pipeline.py"],
        "current_state": {
            "current_scope": "frozen_phase1_model_comparison_and_promotion_rules",
            "runtime_surface": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "status": "deferred_target_architecture_only",
        },
    },
    "validation": {
        "current_authority_includes": [
            "docs/phase1-research-spec.md",
            "docs/phase1-execution-roadmap.md",
            "Pipeline.py",
        ],
        "current_state": {
            "current_scope": "frozen_phase1_threshold_family_and_stitched_outer_test_validation",
            "runtime_surface": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "validation_geometry": "purged_walk_forward_cv_756d_21d_20d_embargo",
            "status": "deferred_target_architecture_only",
        },
    },
    "portfolio": {
        "current_authority_includes": ["docs/phase1-research-spec.md", "Pipeline.py"],
        "current_state": {
            "current_scope": "frozen_phase1_fixed_8_cap_threshold_policy_portfolio",
            "runtime_surface": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "portfolio_construction": "sector_neutral_market_neutral_long_short_top_150_ADV",
            "status": "deferred_target_architecture_only",
        },
    },
    "monitoring": {
        "current_authority_includes": [
            "docs/phase1-research-spec.md",
            "docs/phase1-execution-roadmap.md",
            "Pipeline.py",
        ],
        "current_state": {
            "current_scope": "phase1_run_validity_and_artifact_reporting",
            "runtime_surface": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "retraining_frequency": "weekly",
            "status": "deferred_target_architecture_only",
        },
    },
    "reports": {
        "current_authority_includes": ["README.md", "docs/phase1-research-spec.md", "strategy-report.qmd"],
        "current_state": {
            "current_scope": "phase1_artifact_bundle_and_strategy_report",
            "runtime_surface": "Pipeline.py",
        },
        "deferred_authority": [TARGET_SPEC_RELATIVE],
        "deferred_state": {
            "status": "deferred_target_architecture_only",
        },
    },
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(_read_text(path))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected YAML object at {path}")
    return payload


def _as_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _add_missing_snippets(path: str, text: str, snippets: list[str], errors: list[str]) -> None:
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        errors.append(f"{path} missing required snippets: {missing}")


def _check_markdown(root: Path, errors: list[str]) -> None:
    for relative_path, snippets in EXPECTED_MARKDOWN_SNIPPETS.items():
        path = root / relative_path
        if not path.exists():
            errors.append(f"Missing scoped-canon doc: {relative_path}")
            continue
        _add_missing_snippets(relative_path, _read_text(path), snippets, errors)

    for relative_path, snippets in EXPECTED_LOWER_DOC_REFERENCES.items():
        path = root / relative_path
        if not path.exists():
            errors.append(f"Missing lower-precedence doc: {relative_path}")
            continue
        _add_missing_snippets(relative_path, _read_text(path), snippets, errors)


def _check_precedence_block(data: dict[str, Any], mirror_id: str, errors: list[str]) -> None:
    precedence = data.get("precedence")
    if not isinstance(precedence, dict):
        errors.append(f"{mirror_id}.yaml missing precedence object")
        return

    higher = _as_string_list(precedence.get("higher_priority_authorities"))
    if higher != COMMON_HIGHER_AUTHORITIES:
        errors.append(f"{mirror_id}.yaml higher_priority_authorities mismatch: {higher}")

    if precedence.get("preserved_runtime_surface") != "Pipeline.py":
        errors.append(f"{mirror_id}.yaml preserved_runtime_surface must be Pipeline.py")

    lower = _as_string_list(precedence.get("lower_precedence_surfaces"))
    if lower != LOWER_PRECEDENCE_DOCS:
        errors.append(f"{mirror_id}.yaml lower_precedence_surfaces mismatch: {lower}")


def _check_state_block(
    *,
    block_name: str,
    block: Any,
    mirror_id: str,
    errors: list[str],
) -> tuple[list[str] | None, dict[str, Any] | None]:
    if not isinstance(block, dict):
        errors.append(f"{mirror_id}.yaml missing {block_name} object")
        return None, None

    authority = _as_string_list(block.get("authority"))
    if authority is None:
        errors.append(f"{mirror_id}.yaml {block_name}.authority must be a string list")

    state_key = "implemented_state" if block_name == "effective_current_canon" else "target_state"
    state = block.get(state_key)
    if not isinstance(state, dict):
        errors.append(f"{mirror_id}.yaml {block_name}.{state_key} must be an object")
        state = None

    return authority, state


def _check_mirror(root: Path, mirror_id: str, spec: dict[str, Any], errors: list[str]) -> None:
    path = root / "config" / "canonical" / f"{mirror_id}.yaml"
    if not path.exists():
        errors.append(f"Missing mirror file: config/canonical/{mirror_id}.yaml")
        return

    data = _load_yaml(path)
    required_top_level = {
        "schema_version",
        "mirror_id",
        "scoped_canon_source",
        "area_status",
        "precedence",
        "effective_current_canon",
        "deferred_target_canon",
    }
    missing = sorted(required_top_level - set(data))
    if missing:
        errors.append(f"{mirror_id}.yaml missing top-level keys: {missing}")
        return

    if data.get("schema_version") != 1:
        errors.append(f"{mirror_id}.yaml schema_version must be 1")
    if data.get("mirror_id") != mirror_id:
        errors.append(f"{mirror_id}.yaml mirror_id mismatch")
    if data.get("scoped_canon_source") != DIRECTIVE_RELATIVE:
        errors.append(f"{mirror_id}.yaml scoped_canon_source mismatch")
    if data.get("area_status") != "mixed_current_and_deferred":
        errors.append(f"{mirror_id}.yaml area_status must be mixed_current_and_deferred")

    _check_precedence_block(data, mirror_id, errors)

    current_authority, current_state = _check_state_block(
        block_name="effective_current_canon",
        block=data.get("effective_current_canon"),
        mirror_id=mirror_id,
        errors=errors,
    )
    deferred_authority, deferred_state = _check_state_block(
        block_name="deferred_target_canon",
        block=data.get("deferred_target_canon"),
        mirror_id=mirror_id,
        errors=errors,
    )

    if current_authority is not None:
        missing_current = [
            authority for authority in spec["current_authority_includes"] if authority not in current_authority
        ]
        if missing_current:
            errors.append(f"{mirror_id}.yaml missing effective current authorities: {missing_current}")

    if deferred_authority != spec["deferred_authority"]:
        errors.append(f"{mirror_id}.yaml deferred authority mismatch: {deferred_authority}")

    if current_state is not None:
        for key, expected in spec["current_state"].items():
            if current_state.get(key) != expected:
                errors.append(f"{mirror_id}.yaml current state mismatch for {key}: {current_state.get(key)!r}")

    if deferred_state is not None:
        for key, expected in spec["deferred_state"].items():
            if deferred_state.get(key) != expected:
                errors.append(f"{mirror_id}.yaml deferred state mismatch for {key}: {deferred_state.get(key)!r}")
        status = deferred_state.get("status")
        if not isinstance(status, str) or not status.startswith("deferred"):
            errors.append(f"{mirror_id}.yaml deferred status must start with deferred")


def collect_errors(project_root: Path | None = None) -> list[str]:
    root = project_root or PROJECT_ROOT
    errors: list[str] = []
    _check_markdown(root, errors)
    for mirror_id, spec in MIRROR_SPECS.items():
        _check_mirror(root, mirror_id, spec, errors)
    return errors


def run_checks(project_root: Path | None = None) -> int:
    errors = collect_errors(project_root)
    if errors:
        raise SystemExit("scoped canon drift detected:\n- " + "\n- ".join(errors))
    print("scoped_canon_ok")
    return 0


def main() -> int:
    return run_checks()


if __name__ == "__main__":
    raise SystemExit(main())
