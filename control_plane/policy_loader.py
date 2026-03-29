from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from .models import LoadedPolicy, cast_mapping

CANONICAL_POLICY_BEGIN = "<!-- BEGIN_CANONICAL_POLICY -->"
CANONICAL_POLICY_END = "<!-- END_CANONICAL_POLICY -->"
DEFAULT_BOOTSTRAP_PIN_PATH = Path("contracts/bootstrap_pin.lock.json")
LEGACY_EXTERNAL_PIN_PATH = Path("contracts/policy_fingerprint.lock.json")
DEFAULT_POLICY_PATH = Path("AGENTS.md")
DEFAULT_LOADER_MANIFEST_PATH = Path("control_plane/loader_manifest.json")


class PolicyBootstrapError(RuntimeError):
    """Raised when canonical policy bootstrap validation fails."""


def compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_sha256_file(path: Path) -> str:
    return compute_sha256_bytes(path.read_bytes())


def extract_canonical_policy_text(markdown: str) -> str:
    if CANONICAL_POLICY_BEGIN not in markdown or CANONICAL_POLICY_END not in markdown:
        raise PolicyBootstrapError("AGENTS.md is missing canonical policy markers")

    start = markdown.index(CANONICAL_POLICY_BEGIN) + len(CANONICAL_POLICY_BEGIN)
    end = markdown.index(CANONICAL_POLICY_END, start)
    body = markdown[start:end].strip()

    if body.startswith("```json"):
        body = body[len("```json") :].strip()
    if body.endswith("```"):
        body = body[:-3].strip()
    return body


def normalize_policy_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_policy_fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
    return compute_sha256_bytes(normalize_policy_json(payload).encode("utf-8"))


def _bootstrap_policy_value(payload: Mapping[str, Any], key: str, default: str) -> str:
    bootstrap = cast_mapping(payload.get("bootstrap_policy", {}))
    value = bootstrap.get(key, default)
    return str(value)


def _load_governance_registries(project_root: Path, payload: Mapping[str, Any]) -> tuple[Path, Mapping[str, Any]]:
    registries = cast_mapping(payload.get("governance_registries", {}))
    relative_path = Path(str(registries.get("path", "control_plane/governance_registries.json")))
    target = project_root / relative_path
    if not target.exists():
        raise PolicyBootstrapError(f"Governance registries missing: {target}")
    parsed = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise PolicyBootstrapError(f"Governance registries payload is not a JSON object: {target}")
    return target, parsed


def compute_loader_manifest_hash(project_root: Path) -> str:
    return compute_sha256_file(project_root / DEFAULT_LOADER_MANIFEST_PATH)


def build_policy_fingerprint_lock_payload(project_root: Path, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    project_root = project_root.resolve()
    policy_path = project_root / DEFAULT_POLICY_PATH
    return {
        "policy_path": str(policy_path.relative_to(project_root)),
        "policy_fingerprint": compute_policy_fingerprint_from_payload(payload),
        "policy_version": payload.get("policy_version"),
    }


def write_policy_fingerprint_lock(
    project_root: Path,
    payload: Mapping[str, Any],
    *,
    destination: Optional[Path] = None,
) -> Path:
    project_root = project_root.resolve()
    target = destination or (project_root / LEGACY_EXTERNAL_PIN_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_policy_fingerprint_lock_payload(project_root, payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _resolve_bootstrap_pin_path(project_root: Path, payload: Mapping[str, Any]) -> Path:
    file_env_var_name = _bootstrap_policy_value(payload, "external_bootstrap_pin_file_env", "CODEX_BOOTSTRAP_PIN_FILE")
    default_pin_relative = Path(_bootstrap_policy_value(payload, "external_bootstrap_pin_default", str(DEFAULT_BOOTSTRAP_PIN_PATH)))
    file_override = os.environ.get(file_env_var_name)
    if file_override:
        pin_path = Path(file_override)
        if not pin_path.is_absolute():
            pin_path = project_root / pin_path
        return pin_path
    return project_root / default_pin_relative


def load_bootstrap_pin(
    project_root: Path,
    payload: Mapping[str, Any],
    *,
    allow_legacy: bool,
) -> tuple[Optional[Path], Optional[Mapping[str, Any]]]:
    pin_path = _resolve_bootstrap_pin_path(project_root, payload)
    if pin_path.exists():
        parsed = json.loads(pin_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, Mapping):
            raise PolicyBootstrapError(f"Bootstrap pin is not a JSON object: {pin_path}")
        policy_fingerprint = parsed.get("policy_fingerprint")
        loader_manifest_hash = parsed.get("loader_manifest_hash")
        if not isinstance(policy_fingerprint, str) or not policy_fingerprint.strip():
            raise PolicyBootstrapError(f"Invalid bootstrap pin file: {pin_path}")
        if not isinstance(loader_manifest_hash, str) or not loader_manifest_hash.strip():
            raise PolicyBootstrapError(f"Bootstrap pin is missing loader_manifest_hash: {pin_path}")
        return pin_path, parsed

    if not allow_legacy:
        return pin_path, None

    legacy_env_name = _bootstrap_policy_value(payload, "legacy_external_policy_pin_file_env", "CODEX_POLICY_FINGERPRINT_FILE")
    legacy_default = Path(_bootstrap_policy_value(payload, "legacy_external_policy_pin_default", str(LEGACY_EXTERNAL_PIN_PATH)))
    legacy_override = os.environ.get(legacy_env_name)
    if legacy_override:
        legacy_path = Path(legacy_override)
        if not legacy_path.is_absolute():
            legacy_path = project_root / legacy_path
    else:
        legacy_path = project_root / legacy_default
    if not legacy_path.exists():
        return None, None

    parsed = json.loads(legacy_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise PolicyBootstrapError(f"Legacy bootstrap pin is not a JSON object: {legacy_path}")
    fingerprint = parsed.get("policy_fingerprint", parsed.get("fingerprint"))
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise PolicyBootstrapError(f"Legacy bootstrap pin is missing fingerprint: {legacy_path}")
    return legacy_path, {
        "policy_fingerprint": fingerprint.strip(),
        "loader_manifest_hash": None,
        "format": "policy_fingerprint_only",
    }


def verify_loader_manifest(project_root: Path, *, expected_manifest_hash: Optional[str] = None) -> str:
    manifest_path = project_root / DEFAULT_LOADER_MANIFEST_PATH
    if not manifest_path.exists():
        raise PolicyBootstrapError(f"Loader manifest missing: {manifest_path}")

    manifest_hash = compute_sha256_file(manifest_path)
    if expected_manifest_hash and expected_manifest_hash != manifest_hash:
        raise PolicyBootstrapError(
            "Loader manifest hash mismatch: "
            f"expected {expected_manifest_hash}, got {manifest_hash}"
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, Mapping):
        raise PolicyBootstrapError("Loader manifest does not contain a valid files mapping")

    mismatches: list[str] = []
    for relative_path, expected_hash in files.items():
        target = project_root / str(relative_path)
        if not target.exists():
            mismatches.append(f"missing:{relative_path}")
            continue
        actual_hash = compute_sha256_file(target)
        if actual_hash != expected_hash:
            mismatches.append(f"hash:{relative_path}")

    if mismatches:
        raise PolicyBootstrapError("Loader integrity mismatch: " + ", ".join(mismatches))
    return manifest_hash


def load_canonical_policy_payload(policy_path: Path) -> Mapping[str, Any]:
    markdown = policy_path.read_text(encoding="utf-8")
    canonical_text = extract_canonical_policy_text(markdown)
    payload = json.loads(canonical_text)
    if not isinstance(payload, Mapping):
        raise PolicyBootstrapError("Canonical policy payload is not a JSON object")
    return payload


def load_bootstrapped_policy(
    project_root: Path,
    *,
    require_external_pin: bool = True,
    verify_loader: bool = True,
) -> LoadedPolicy:
    project_root = project_root.resolve()
    policy_path = project_root / DEFAULT_POLICY_PATH
    if not policy_path.exists():
        raise PolicyBootstrapError(f"Canonical policy file missing: {policy_path}")

    payload = load_canonical_policy_payload(policy_path)
    declared_manifest = Path(_bootstrap_policy_value(payload, "loader_manifest_path", str(DEFAULT_LOADER_MANIFEST_PATH)))
    if declared_manifest != DEFAULT_LOADER_MANIFEST_PATH:
        raise PolicyBootstrapError(
            f"Bootstrap policy loader_manifest_path must remain {DEFAULT_LOADER_MANIFEST_PATH}, got {declared_manifest}"
        )
    canonical_json = normalize_policy_json(payload)
    fingerprint = compute_sha256_bytes(canonical_json.encode("utf-8"))
    fail_closed = bool(cast_mapping(payload.get("bootstrap_policy", {})).get("fail_closed", True))
    bootstrap_pin_path, bootstrap_pin = load_bootstrap_pin(project_root, payload, allow_legacy=not require_external_pin)
    expected_fingerprint = None
    expected_loader_manifest_hash = None
    if bootstrap_pin is not None:
        expected_fingerprint = str(bootstrap_pin.get("policy_fingerprint", "")).strip() or None
        loader_manifest_hash = bootstrap_pin.get("loader_manifest_hash")
        if isinstance(loader_manifest_hash, str) and loader_manifest_hash.strip():
            expected_loader_manifest_hash = loader_manifest_hash.strip()

    if verify_loader:
        verify_loader_manifest(project_root, expected_manifest_hash=expected_loader_manifest_hash)

    if require_external_pin:
        if not expected_fingerprint:
            raise PolicyBootstrapError(
                "External policy fingerprint pin missing; run trust-policy before startup"
            )
        if not expected_loader_manifest_hash:
            raise PolicyBootstrapError(
                "Bootstrap pin is missing loader_manifest_hash; rerun trust-policy to migrate the pin format"
            )
        if expected_fingerprint != fingerprint:
            raise PolicyBootstrapError(
                f"Policy fingerprint mismatch: expected {expected_fingerprint}, got {fingerprint}"
            )
    elif fail_closed and expected_fingerprint and expected_fingerprint != fingerprint:
        raise PolicyBootstrapError(
            f"Policy fingerprint mismatch: expected {expected_fingerprint}, got {fingerprint}"
        )

    governance_registries_path, governance_registries = _load_governance_registries(project_root, payload)

    return LoadedPolicy(
        project_root=project_root,
        policy_path=policy_path,
        raw_policy=payload,
        canonical_json=canonical_json,
        fingerprint=fingerprint,
        expected_fingerprint=expected_fingerprint,
        expected_loader_manifest_hash=expected_loader_manifest_hash,
        bootstrap_pin_path=bootstrap_pin_path,
        governance_registries_path=governance_registries_path,
        governance_registries=governance_registries,
    )


def trust_current_policy(project_root: Path, *, pin_path: Optional[Path] = None) -> Path:
    project_root = project_root.resolve()
    manifest_hash = verify_loader_manifest(project_root)
    policy_path = project_root / DEFAULT_POLICY_PATH
    if not policy_path.exists():
        raise PolicyBootstrapError(f"Canonical policy file missing: {policy_path}")
    payload = load_canonical_policy_payload(policy_path)
    fingerprint = compute_policy_fingerprint_from_payload(payload)

    default_pin_relative = Path(
        _bootstrap_policy_value(payload, "external_bootstrap_pin_default", str(DEFAULT_BOOTSTRAP_PIN_PATH))
    )
    destination = project_root / (pin_path or default_pin_relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pin_payload = {
        "policy_fingerprint": fingerprint,
        "loader_manifest_hash": manifest_hash,
        "policy_path": str(policy_path.relative_to(project_root)),
        "policy_version": payload.get("policy_version"),
    }
    destination.write_text(json.dumps(pin_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_policy_fingerprint_lock(project_root, payload)
    return destination
