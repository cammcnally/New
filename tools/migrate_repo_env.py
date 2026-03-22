from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
SECRET_KEYS = (
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "MCP_PROXY_AUTH_TOKEN",
)
CANONICAL_SECRET_KEYS = {key.upper(): key for key in SECRET_KEYS}


def _strip_matching_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _persist_user_env(name: str, value: str) -> None:
    if os.name != "nt":
        raise RuntimeError("User-scope environment migration is only automated on Windows")
    result = subprocess.run(
        ["setx", name, value],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to persist {name!r} to the user environment: {result.stderr.strip()}")


def migrate_repo_env() -> dict[str, object]:
    if not ENV_PATH.exists():
        return {"env_exists": False, "migrated_keys": [], "rewritten_env": False}

    if ENV_PATH.is_dir():
        migrated_keys: list[str] = []
        for child in ENV_PATH.iterdir():
            if not child.is_file():
                continue
            canonical_key = CANONICAL_SECRET_KEYS.get(child.name.upper())
            if canonical_key is None:
                continue
            value = child.read_text(encoding="utf-8").strip()
            if not value:
                continue
            _persist_user_env(canonical_key, value)
            migrated_keys.append(canonical_key)
            child.unlink()
        if not any(ENV_PATH.iterdir()):
            ENV_PATH.rmdir()
        return {
            "env_exists": True,
            "layout": "directory",
            "migrated_keys": migrated_keys,
            "rewritten_env": bool(migrated_keys),
        }

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    kept_lines: list[str] = []
    migrated_keys: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            kept_lines.append(line)
            continue
        name, raw_value = stripped.split("=", 1)
        key = name.strip()
        value = _strip_matching_quotes(raw_value)
        canonical_key = CANONICAL_SECRET_KEYS.get(key.upper())
        if canonical_key is not None and value:
            _persist_user_env(canonical_key, value)
            migrated_keys.append(canonical_key)
            continue
        kept_lines.append(line)

    if migrated_keys:
        banner = [
            "# Secrets migrated out of repo-local .env",
            "# The following keys now live in the user environment:",
            *[f"# - {name}" for name in migrated_keys],
            "# Restart shells and editor-integrated terminals to pick up the new values.",
            "",
        ]
        ENV_PATH.write_text("\n".join(banner + kept_lines).rstrip() + "\n", encoding="utf-8")

    return {
        "env_exists": True,
        "layout": "file",
        "migrated_keys": migrated_keys,
        "rewritten_env": bool(migrated_keys),
    }


def main() -> int:
    result = migrate_repo_env()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
