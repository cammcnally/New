from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_plane.models import ActionSpec, ApprovalClass
from control_plane.runtime_env import LoadedSecret, _python_version_is_supported, resolve_git_executable
from control_plane.orchestrator import CodexControlPlane, RepoActionRunner
from control_plane.policy_loader import compute_loader_manifest_hash, compute_policy_fingerprint_from_payload, load_canonical_policy_payload
from control_plane.task_state import current_git_commit
from tools import control_plane as control_plane_cli


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


def test_control_plane_entrypoint_python_guards_reject_out_of_range_versions() -> None:
    control_plane_cli._require_supported_python_version((3, 11, 9))
    assert _python_version_is_supported((3, 11, 9), "3.11.9") is True
    assert _python_version_is_supported((3, 11, 11), "3.11.9") is True
    assert _python_version_is_supported((3, 12, 0), "3.11.9") is False
    with pytest.raises(SystemExit):
        control_plane_cli._require_supported_python_version((3, 12, 2))


def test_resolve_git_executable_prefers_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "NEW"
    project_root.mkdir()
    monkeypatch.setattr("control_plane.runtime_env.shutil.which", lambda *_args, **_kwargs: r"E:\portable\git\cmd\git.exe")

    assert resolve_git_executable(project_root) == r"E:\portable\git\cmd\git.exe"


def test_resolve_git_executable_falls_back_to_repo_adjacent_portable_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "NEW"
    project_root.mkdir()
    portable_git = tmp_path / "Git" / "cmd" / "git.exe"
    portable_git.parent.mkdir(parents=True, exist_ok=True)
    portable_git.write_text("", encoding="utf-8")
    monkeypatch.setattr("control_plane.runtime_env.shutil.which", lambda *_args, **_kwargs: None)

    assert Path(resolve_git_executable(project_root)).resolve() == portable_git.resolve()


def test_current_git_commit_uses_resolved_git(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr("control_plane.task_state.resolve_git_executable", lambda *_args, **_kwargs: "portable-git")

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        seen["command"] = command
        return SimpleNamespace(stdout="abc123\n")

    monkeypatch.setattr("control_plane.task_state.subprocess.run", fake_run)

    assert current_git_commit(PROJECT_ROOT) == "abc123"
    assert seen["command"] == ["portable-git", "rev-parse", "HEAD"]


def test_repo_change_collectors_use_resolved_git(monkeypatch: pytest.MonkeyPatch) -> None:
    cli_seen: dict[str, object] = {}
    orchestrator_seen: dict[str, object] = {}

    monkeypatch.setattr(control_plane_cli, "resolve_git_executable", lambda *_args, **_kwargs: "portable-git")

    def fake_cli_run(command: list[str], **_: object) -> SimpleNamespace:
        cli_seen["command"] = command
        return SimpleNamespace(stdout=" M README.md\n?? notes.txt\n")

    monkeypatch.setattr(control_plane_cli.subprocess, "run", fake_cli_run)
    assert control_plane_cli._collect_repo_changes() == ["README.md", "notes.txt"]
    assert cli_seen["command"] == ["portable-git", "status", "--short"]

    monkeypatch.setattr("control_plane.orchestrator.resolve_git_executable", lambda *_args, **_kwargs: "portable-git")

    def fake_orchestrator_run(command: list[str], **_: object) -> SimpleNamespace:
        orchestrator_seen["command"] = command
        return SimpleNamespace(stdout=" M README.md\n")

    monkeypatch.setattr("control_plane.orchestrator.subprocess.run", fake_orchestrator_run)
    control_plane = object.__new__(CodexControlPlane)
    control_plane.project_root = PROJECT_ROOT
    control_plane.policy = SimpleNamespace(runtime_environment={})
    assert control_plane._collect_repo_changes() == ["README.md"]
    assert orchestrator_seen["command"] == ["portable-git", "status", "--short"]


def test_repo_action_runner_rejects_non_auto_approved_shell_actions() -> None:
    action = ActionSpec(
        name="sensitive_shell",
        kind="shell_template",
        command=("echo", "hello"),
        allowed_roles=("Runner",),
        approval=ApprovalClass.REQUIRES_HUMAN,
        sensitive=True,
        timeout_seconds=10,
    )
    policy = SimpleNamespace(action_for=lambda _name: action)
    runner = RepoActionRunner(PROJECT_ROOT, policy)

    with pytest.raises(PermissionError):
        runner.run_shell_action("Runner", "sensitive_shell", {})
