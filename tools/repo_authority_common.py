from __future__ import annotations

import json
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "config" / "canonical" / "repo_authority.yaml"
FROZEN_HASHES_PATH = PROJECT_ROOT / "config" / "canonical" / "frozen_surface_hashes.json"
MANDATORY_ENFORCEMENT_SENTENCE = (
    "No repository rule is valid unless it is enforced by canonical files, machine-readable registry, "
    "verifier scripts, tests, runtime loaders, or CI failure gates."
)

REQUIRED_BUCKETS = (
    "protected_authorities",
    "frozen_boundary_only",
    "generated_shims",
    "generated_outputs",
    "live_runtime",
    "compatibility_only",
    "optional_secondary",
    "merge_demote_candidates",
)

MANDATORY_BUCKET_VALUES: dict[str, tuple[str, ...]] = {
    "protected_authorities": (
        "AGENTS.md",
        "docs/data_contract.md",
        "docs/phase1-research-spec.md",
        "docs/phase1-execution-roadmap.md",
        "README.md",
    ),
    "frozen_boundary_only": (
        "Pipeline.py",
        "tools/phase1_sanity_check.py",
        "feature_registry/**",
        "tests/test_phase1_*.py",
    ),
    "generated_shims": (
        ".cursor/**",
        "contracts/*.lock.json",
    ),
    "generated_outputs": (
        "panel_ohlcv_clean.csv",
        "**/*.manifest.json",
        "data_lake/manifests/**",
        "data_lake/**/benchmark_surface_daily*",
        "generated/**",
        "projections/**",
    ),
    "live_runtime": (
        "market_data/**",
        "control_plane/**",
        "tools/control_plane.py",
        "tools/verify_market_data_contracts.py",
        "market_data/common/schema_registry.py",
        "market_data/common/pandera_contracts.py",
        "strategy-report.qmd",
        ".github/workflows/**",
    ),
    "compatibility_only": (
        "market_data/silver/security_master",
        "market_data/bridge/**",
        "panel_ohlcv_clean.csv",
    ),
    "optional_secondary": (
        "mlflow_integration/**",
        "lineage/**",
        "gx/**",
        "dvc.yaml",
        "analysis/**",
    ),
    "merge_demote_candidates": (
        "docs/plans/**",
        "docs/checklists/**",
        "docs/workplans/**",
        "docs/archive_candidates/**",
        "docs/COMBINED_IMPLEMENTATION_DIRECTIVE_v1.md",
        "docs/2026-04-03-benchmark-architecture-implementation-plan.md",
        "docs/benchmark_architecture_first_compliant_checklist.md",
    ),
}

EXPLICIT_MULTI_CLASS_ALLOWED: dict[str, set[str]] = {
    "panel_ohlcv_clean.csv": {"generated_outputs", "compatibility_only"},
}

DEMOTION_BANNER = (
    "Status: Non-authoritative work artifact\n"
    "Canonical authority:\n"
    "- AGENTS.md\n"
    "- docs/data_contract.md\n"
    "- docs/phase1-research-spec.md\n"
    "- docs/phase1-execution-roadmap.md\n"
)

GENERATED_AUTHORITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsource[_ ]of[_ ]truth\b", re.IGNORECASE),
    re.compile(r"\bcanonical policy\b", re.IGNORECASE),
    re.compile(r"\bauthoritative\b", re.IGNORECASE),
    re.compile(r"\bmust follow this\b", re.IGNORECASE),
    re.compile(r"\bcanonical authority\b", re.IGNORECASE),
)

SECONDARY_DOC_SELF_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("source_of_truth_claim", re.compile(r"\bsource of truth\b", re.IGNORECASE)),
    ("active_working_plan", re.compile(r"\bactive working plan\b", re.IGNORECASE)),
    ("canonical_working_checklist", re.compile(r"\bcanonical working checklist\b", re.IGNORECASE)),
    ("supersedes_claim", re.compile(r"\bsupersedes\b", re.IGNORECASE)),
    ("authoritative_runbook", re.compile(r"\bThis is the authoritative\b", re.IGNORECASE)),
    ("authoritative_entrypoint", re.compile(r"\bauthoritative (?:e2e|local command|entrypoint|flow)\b", re.IGNORECASE)),
    ("document_defines_concern", re.compile(r"\bThis document defines\b", re.IGNORECASE)),
    ("file_defines_concern", re.compile(r"\bThis file defines\b", re.IGNORECASE)),
)

SECONDARY_DOC_PATHS = (
    "docs/end_to_end_trading_system_architecture.md",
    "docs/implementation_runbook.md",
    "docs/market_data_roadmap.md",
    "docs/contract-inventory.md",
    "docs/PROJECT_OUTCOME.md",
    "docs/repo_cleanup_policy.md",
    "docs/run_status.md",
)


def normalize_path(path: str | Path) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).as_posix()


def project_relative(path: Path) -> str:
    return normalize_path(path.relative_to(PROJECT_ROOT))


def run_git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def tracked_files() -> list[str]:
    return [normalize_path(item) for item in run_git_lines("ls-files")]


def file_text_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def parse_string_list_yaml(text: str) -> dict[str, object]:
    data: dict[str, object] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            if ":" not in line:
                raise SystemExit(f"Invalid registry line: {raw_line}")
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                if key == "version":
                    try:
                        data[key] = int(value)
                    except ValueError as exc:
                        raise SystemExit(f"Registry version must be integer: {value}") from exc
                else:
                    data[key] = _strip_quotes(value)
                current_key = None
            else:
                data[key] = []
                current_key = key
        else:
            if current_key is None:
                raise SystemExit(f"Unexpected indented line without list key: {raw_line}")
            if not stripped.startswith("- "):
                raise SystemExit(f"Expected list item starting with '- ': {raw_line}")
            items = data[current_key]
            if not isinstance(items, list):
                raise SystemExit(f"Registry key {current_key} is not a list")
            items.append(_strip_quotes(stripped[2:].strip()))
    return data


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_repo_authority_registry(path: Path | None = None) -> dict[str, object]:
    registry_path = path or REGISTRY_PATH
    payload = parse_string_list_yaml(registry_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise SystemExit(f"{normalize_path(registry_path)} must set version: 1")
    for bucket in REQUIRED_BUCKETS:
        values = payload.get(bucket)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise SystemExit(f"{normalize_path(registry_path)} bucket {bucket} must be a list of strings")
        required = set(MANDATORY_BUCKET_VALUES[bucket])
        if not required.issubset(set(values)):
            missing = sorted(required - set(values))
            raise SystemExit(f"{normalize_path(registry_path)} bucket {bucket} missing required entries: {missing}")
    return payload


def registry_patterns(registry: dict[str, object], bucket: str) -> list[str]:
    values = registry.get(bucket, [])
    if not isinstance(values, list):
        return []
    return [normalize_path(item) for item in values]


def iter_registry_patterns(registry: dict[str, object]) -> Iterable[tuple[str, str]]:
    for bucket in REQUIRED_BUCKETS:
        for pattern in registry_patterns(registry, bucket):
            yield bucket, pattern


def path_matches(path: str | Path, pattern: str) -> bool:
    return fnmatch(normalize_path(path), normalize_path(pattern))


def classify_path(path: str | Path, registry: dict[str, object]) -> list[str]:
    normalized = normalize_path(path)
    matches = [bucket for bucket, pattern in iter_registry_patterns(registry) if path_matches(normalized, pattern)]
    return matches


def is_allowed_multiclass(path: str | Path, buckets: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    allowed = EXPLICIT_MULTI_CLASS_ALLOWED.get(normalized)
    if allowed is None:
        return False
    return set(buckets) == allowed


def governed_candidate_paths(registry: dict[str, object]) -> set[str]:
    candidates: set[str] = set()
    tracked = tracked_files()
    for tracked_path in tracked:
        if classify_path(tracked_path, registry):
            candidates.add(tracked_path)
            continue
        if tracked_path in {
            "AGENTS.md",
            "README.md",
            "Pipeline.py",
            "panel_ohlcv_clean.csv",
            "panel_ohlcv_clean.csv.manifest.json",
        }:
            candidates.add(tracked_path)
            continue
        if tracked_path.startswith(("docs/governance/", "config/canonical/", "tests/acceptance/", ".cursor/", ".github/workflows/")):
            candidates.add(tracked_path)
    return candidates


def load_frozen_hashes(path: Path | None = None) -> dict[str, object]:
    frozen_path = path or FROZEN_HASHES_PATH
    payload = json.loads(frozen_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{normalize_path(frozen_path)} must contain a JSON object")
    return payload
