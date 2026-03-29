from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class RuntimeEnvironmentError(RuntimeError):
    """Raised when the control-plane runtime environment is invalid."""


@dataclass(frozen=True)
class LoadedSecret:
    source_label: str
    source_path: Path | None
    exported_names: tuple[str, ...]


PORTABLE_GIT_RELATIVE_CANDIDATES = (
    Path("Git/cmd/git.exe"),
    Path("Git/bin/git.exe"),
    Path("Git/mingw64/bin/git.exe"),
)
DEFAULT_GIT_ENV_VAR_NAMES = ("CODEX_GIT_EXECUTABLE", "GIT_EXECUTABLE")


def _runtime_policy_value(runtime_policy: Mapping[str, Any], key: str, default: str) -> str:
    return str(runtime_policy.get(key, default))


def _read_expected_python_version(project_root: Path, runtime_policy: Mapping[str, Any]) -> str:
    policy_value = runtime_policy.get("required_python_version")
    if isinstance(policy_value, str) and policy_value.strip():
        return policy_value.strip()
    python_version_path = project_root / ".python-version"
    if not python_version_path.exists():
        raise RuntimeEnvironmentError(f"Missing required Python version file: {python_version_path}")
    return python_version_path.read_text(encoding="utf-8").strip()


def _parse_version_tuple(raw_version: str) -> tuple[int, int, int]:
    parts = raw_version.strip().split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise RuntimeEnvironmentError(f"Invalid required Python version: {raw_version}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _python_range_text(minimum: tuple[int, int, int]) -> str:
    return f">={minimum[0]}.{minimum[1]}.{minimum[2]},<{minimum[0]}.{minimum[1] + 1}"


def _python_version_is_supported(actual: tuple[int, int, int], required_python: str) -> bool:
    minimum = _parse_version_tuple(required_python)
    upper = (minimum[0], minimum[1] + 1, 0)
    return actual >= minimum and actual < upper


def _git_env_var_names(runtime_policy: Mapping[str, Any] | None) -> tuple[str, ...]:
    if runtime_policy is None:
        return DEFAULT_GIT_ENV_VAR_NAMES
    raw_names = runtime_policy.get("git_executable_env_vars", DEFAULT_GIT_ENV_VAR_NAMES)
    if not isinstance(raw_names, (list, tuple)):
        return DEFAULT_GIT_ENV_VAR_NAMES
    normalized = tuple(str(item).strip() for item in raw_names if str(item).strip())
    return normalized or DEFAULT_GIT_ENV_VAR_NAMES


def _candidate_git_path(project_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def resolve_git_executable(project_root: Path, runtime_policy: Mapping[str, Any] | None = None) -> str:
    project_root = project_root.resolve()
    candidates: list[Path] = []

    for env_name in _git_env_var_names(runtime_policy):
        raw_value = os.environ.get(env_name)
        if raw_value and raw_value.strip():
            candidates.append(_candidate_git_path(project_root, raw_value.strip()))

    if runtime_policy is not None:
        configured = runtime_policy.get("preferred_git_executable")
        if isinstance(configured, str) and configured.strip():
            candidates.append(_candidate_git_path(project_root, configured.strip()))

    on_path = shutil.which("git")
    if on_path:
        return on_path

    for relative_candidate in PORTABLE_GIT_RELATIVE_CANDIDATES:
        candidates.append((project_root.parent / relative_candidate).resolve())

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "git"


def ensure_repo_runtime(project_root: Path, runtime_policy: Mapping[str, Any]) -> dict[str, str]:
    project_root = project_root.resolve()
    expected_python = _read_expected_python_version(project_root, runtime_policy)
    actual_python = platform.python_version()
    actual_python_tuple = _parse_version_tuple(actual_python)
    minimum_python = _parse_version_tuple(expected_python)
    if not _python_version_is_supported(actual_python_tuple, expected_python):
        raise RuntimeEnvironmentError(
            "Control plane requires Python "
            f"{_python_range_text(minimum_python)}, but current interpreter is {actual_python}"
        )

    venv_relative = Path(_runtime_policy_value(runtime_policy, "required_venv_path", ".venv"))
    expected_venv = (project_root / venv_relative).resolve()
    executable = Path(sys.executable).resolve()
    if expected_venv not in executable.parents:
        raise RuntimeEnvironmentError(
            "Control plane must run from the repo virtual environment "
            f"({expected_venv}), but current interpreter is {executable}"
        )

    env_bootstrap = project_root / Path(_runtime_policy_value(runtime_policy, "env_bootstrap_script", "tools/enter_e_drive_env.ps1"))
    if not env_bootstrap.exists():
        raise RuntimeEnvironmentError(f"Missing environment bootstrap script: {env_bootstrap}")

    return {
        "expected_python_version": _python_range_text(minimum_python),
        "python_executable": str(executable),
        "required_venv_path": str(expected_venv),
        "env_bootstrap_script": str(env_bootstrap),
        "git_executable": resolve_git_executable(project_root, runtime_policy),
    }


def _parse_secret_value(raw_text: str) -> str:
    stripped = raw_text.strip()
    if not stripped:
        raise RuntimeEnvironmentError("Secret file is empty")
    if "\n" not in stripped and "=" in stripped:
        _, value = stripped.split("=", 1)
        stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        stripped = stripped[1:-1]
    if not stripped:
        raise RuntimeEnvironmentError("Secret value is empty after parsing")
    return stripped


def _resolve_secret_from_env(runtime_policy: Mapping[str, Any]) -> tuple[str | None, str | None]:
    candidate_names = runtime_policy.get("required_secret_env", ["CODEX_API_KEY", "OPENAI_API_KEY"])
    for raw_name in candidate_names:
        name = str(raw_name)
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip(), name
    return None, None


def load_repo_secret(project_root: Path, runtime_policy: Mapping[str, Any]) -> LoadedSecret:
    project_root = project_root.resolve()
    secret_value, env_name = _resolve_secret_from_env(runtime_policy)
    source_path: Path | None = None
    source_label: str
    if secret_value is not None:
        source_label = f"user_environment:{env_name}"
    else:
        secret_relative = Path(_runtime_policy_value(runtime_policy, "legacy_secret_file", ".env/Codex_API_KEY"))
        source_path = (project_root / secret_relative).resolve()
        if not source_path.exists():
            raise RuntimeEnvironmentError(f"Missing required secret source: {source_path}")
        raw_text = source_path.read_text(encoding="utf-8")
        secret_value = _parse_secret_value(raw_text)
        source_label = str(source_path.relative_to(project_root)).replace("\\", "/")

    exported_names = ("OPENAI_API_KEY", "CODEX_API_KEY")
    for name in exported_names:
        os.environ[name] = secret_value

    return LoadedSecret(source_label=source_label, source_path=source_path, exported_names=exported_names)
