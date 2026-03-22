from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_plane.runtime_env import LoadedSecret
from control_plane.orchestrator import CodexControlPlane
from control_plane.policy_loader import compute_loader_manifest_hash, compute_policy_fingerprint_from_payload, load_canonical_policy_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_pin(tmp_path: Path, fingerprint: str) -> Path:
    pin = tmp_path / "pin.json"
    pin.write_text(
        json.dumps(
            {
                "policy_fingerprint": fingerprint,
                "loader_manifest_hash": compute_loader_manifest_hash(PROJECT_ROOT),
            }
        ),
        encoding="utf-8",
    )
    return pin


class FakeAgent:
    def __init__(self, *, name: str, model: str, instructions: str, tools: list[object]) -> None:
        self.name = name
        self.model = model
        self.instructions = instructions
        self.tools = tools

    def as_tool(self, tool_name: str, description: str) -> dict[str, str]:
        return {"tool_name": tool_name, "agent_name": self.name, "description": description}


class FakeRunner:
    @staticmethod
    async def run(agent: FakeAgent, input: str) -> SimpleNamespace:
        return SimpleNamespace(final_output=f"{agent.name}:{input}")


@contextmanager
def fake_trace(**_: object):
    yield


def fake_function_tool(func):
    return func


def test_build_agents_includes_dependency_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = load_canonical_policy_payload(PROJECT_ROOT / "AGENTS.md")
    pin_path = _write_pin(tmp_path, compute_policy_fingerprint_from_payload(payload))
    monkeypatch.setenv("CODEX_POLICY_FINGERPRINT_FILE", str(pin_path))
    monkeypatch.setenv("CODEX_BOOTSTRAP_PIN_FILE", str(pin_path))
    monkeypatch.setattr(
        "control_plane.orchestrator._load_agents_sdk",
        lambda: (FakeAgent, FakeRunner, fake_trace, fake_function_tool),
    )
    monkeypatch.setattr(
        "control_plane.orchestrator.ensure_repo_runtime",
        lambda *_args, **_kwargs: {"python_executable": "fake-python"},
    )
    monkeypatch.setattr(
        "control_plane.orchestrator.load_repo_secret",
        lambda *_args, **_kwargs: LoadedSecret(
            source_label="user_environment:CODEX_API_KEY",
            source_path=None,
            exported_names=("OPENAI_API_KEY", "CODEX_API_KEY"),
        ),
    )

    control_plane = CodexControlPlane(PROJECT_ROOT)
    agents = control_plane.build_agents()
    coordinator_tools = agents["Coordinator"].tools
    tool_names = [tool.get("tool_name") if isinstance(tool, dict) else tool.__name__ for tool in coordinator_tools]

    assert "DependencyAgent" in agents
    assert "dependency_agent" in tool_names
    assert "phase1_change_check" in tool_names
    assert "set_terminal_state" in tool_names
    assert "evaluate_cloud_delegation" in tool_names

    coordinator_functions = {tool.__name__: tool for tool in coordinator_tools if callable(tool)}
    delegation = json.loads(
        coordinator_functions["evaluate_cloud_delegation"](
            purpose="background_analysis",
            local_only_reasons_json='["touches_pipeline_logic"]',
        )
    )
    assert delegation["allowed"] is False

    dependency_functions = {tool.__name__: tool for tool in agents["DependencyAgent"].tools if callable(tool)}
    with pytest.raises(PermissionError):
        dependency_functions["install_dependency_under_policy"](package_name="requests")

    builder_functions = {tool.__name__: tool for tool in agents["Builder"].tools if callable(tool)}
    with pytest.raises(PermissionError):
        builder_functions["invoke_codex_backend"](tool_name="not-allowed", arguments_json="{}")
