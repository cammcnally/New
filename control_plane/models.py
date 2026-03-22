from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


class TaskClassification(str, Enum):
    BEHAVIOR_PRESERVING = "behavior_preserving"
    SPEC_IMPLEMENTING = "spec_implementing"
    SPEC_CHANGING = "spec_changing"
    POLICY_CHANGING = "policy_changing"
    OPERATIONAL_ONLY = "operational_only"
    TEST_ONLY = "test_only"
    DOCS_ONLY = "docs_only"


class TerminalState(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    BLOCKED_CLEANLY = "blocked_cleanly"
    PARTIAL_PROGRESS = "partial_progress"


class ApprovalClass(str, Enum):
    AUTO = "auto_approved_by_policy"
    REQUIRES_VERIFIER = "requires_verifier"
    REQUIRES_AUDITOR = "requires_auditor"
    REQUIRES_HUMAN = "requires_human"


@dataclass(frozen=True)
class AgentPolicy:
    name: str
    purpose: str
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    handoff_targets: tuple[str, ...]
    completion_criteria: str

    @classmethod
    def from_mapping(cls, name: str, payload: Mapping[str, Any]) -> "AgentPolicy":
        return cls(
            name=name,
            purpose=str(payload["purpose"]),
            allowed_actions=tuple(str(item) for item in payload.get("allowed_actions", [])),
            forbidden_actions=tuple(str(item) for item in payload.get("forbidden_actions", [])),
            handoff_targets=tuple(str(item) for item in payload.get("handoff_targets", [])),
            completion_criteria=str(payload["completion_criteria"]),
        )


@dataclass(frozen=True)
class ActionSpec:
    name: str
    kind: str
    command: tuple[str, ...]
    allowed_roles: tuple[str, ...]
    approval: ApprovalClass
    sensitive: bool
    timeout_seconds: int

    @classmethod
    def from_mapping(cls, name: str, payload: Mapping[str, Any]) -> "ActionSpec":
        return cls(
            name=name,
            kind=str(payload["kind"]),
            command=tuple(str(item) for item in payload.get("command", [])),
            allowed_roles=tuple(str(item) for item in payload.get("allowed_roles", [])),
            approval=ApprovalClass(str(payload["approval"])),
            sensitive=bool(payload.get("sensitive", False)),
            timeout_seconds=int(payload.get("timeout_seconds", 600)),
        )


@dataclass(frozen=True)
class LoadedPolicy:
    project_root: Path
    policy_path: Path
    raw_policy: Mapping[str, Any]
    canonical_json: str
    fingerprint: str
    expected_fingerprint: Optional[str]
    expected_loader_manifest_hash: Optional[str]
    bootstrap_pin_path: Optional[Path]
    governance_registries_path: Path
    governance_registries: Mapping[str, Any]

    @property
    def agents(self) -> Mapping[str, AgentPolicy]:
        payload = self.raw_policy.get("agents", {})
        return {name: AgentPolicy.from_mapping(name, cast_mapping(spec)) for name, spec in payload.items()}

    @property
    def actions(self) -> Mapping[str, ActionSpec]:
        payload = self.raw_policy.get("actions", {})
        return {name: ActionSpec.from_mapping(name, cast_mapping(spec)) for name, spec in payload.items()}

    def action_for(self, name: str) -> ActionSpec:
        actions = self.actions
        if name not in actions:
            raise KeyError(f"Unknown action: {name}")
        return actions[name]

    def agent_for(self, name: str) -> AgentPolicy:
        agents = self.agents
        if name not in agents:
            raise KeyError(f"Unknown agent: {name}")
        return agents[name]

    @property
    def bootstrap_policy(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("bootstrap_policy", {}))

    @property
    def trace_security(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("trace_security", {}))

    @property
    def task_scaffolding(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("task_scaffolding", {}))

    @property
    def protected_infrastructure(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("protected_infrastructure", {}))

    @property
    def runtime_environment(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("runtime_environment", {}))

    @property
    def dependency_policy(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("dependency_policy", {}))

    @property
    def approval_policy(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("approval_policy", {}))

    @property
    def verifier_store(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("verifier_store", {}))

    @property
    def structured_review(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("structured_review", {}))

    @property
    def delegation_data_classes(self) -> tuple[str, ...]:
        payload = self.raw_policy.get("delegation_data_classes", [])
        return tuple(str(item) for item in payload)

    @property
    def mcp_policy(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("mcp_policy", {}))

    @property
    def skills_registry(self) -> Mapping[str, Any]:
        return cast_mapping(self.raw_policy.get("skills_registry", {}))

    def governance_section(self, section_name: str) -> Mapping[str, Any]:
        return cast_mapping(self.governance_registries.get(section_name, {}))

    def required_task_files(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.task_scaffolding.get("required_files", ()))


@dataclass(frozen=True)
class TaskWorkspace:
    task_id: str
    project_root: Path
    root: Path
    requirements_path: Path
    acceptance_path: Path
    agent_task_path: Path
    brief_path: Path
    classification_path: Path
    summary_path: Path
    handoff_path: Path
    verification_checklist_path: Path
    status_path: Path
    final_result_path: Path
    warning_manifest_path: Path
    environment_path: Path
    trace_path: Path
    execplan_path: Path
    approval_requirements_path: Path
    review_outputs_path: Path
    verifier_path: Path
    state_log_path: Path
    manifest_path: Path

    def tracked_paths(self) -> tuple[Path, ...]:
        return (
            self.requirements_path,
            self.acceptance_path,
            self.agent_task_path,
            self.brief_path,
            self.classification_path,
            self.summary_path,
            self.handoff_path,
            self.verification_checklist_path,
            self.status_path,
            self.final_result_path,
            self.warning_manifest_path,
            self.environment_path,
            self.trace_path,
            self.execplan_path,
            self.approval_requirements_path,
            self.review_outputs_path,
            self.verifier_path,
            self.state_log_path,
            self.manifest_path,
        )


def cast_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected mapping, got: {type(value)!r}")
    return value


def ensure_allowed_role(action: ActionSpec, role: str) -> None:
    if role not in action.allowed_roles:
        raise PermissionError(f"Role {role!r} may not execute action {action.name!r}")


def render_command(template: Sequence[str], substitutions: Mapping[str, Any]) -> list[str]:
    rendered: list[str] = []
    for part in template:
        value = part
        for key, replacement in substitutions.items():
            value = value.replace("{" + key + "}", str(replacement))
        rendered.append(value)
    return rendered
