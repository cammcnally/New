from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Mapping

from .policy_loader import load_canonical_policy_payload


def _compat_banner(title: str) -> str:
    return dedent(
        f"""\
        # {title}

        This `.cursor` file is a local compatibility shim only.
        Canonical authority lives in `AGENTS.md`, `docs/phase1-research-spec.md`, `docs/phase1-execution-roadmap.md`, and `README.md`.
        Never let this file broaden or override canonical policy.
        """
    )


def _mdc(title: str, description: str, body: str) -> str:
    return (
        "---\n"
        f"description: {description}\n"
        "alwaysApply: true\n"
        "---\n\n"
        + _compat_banner(title)
        + "\n"
        + body.strip()
        + "\n"
    )


def build_cursor_projection(project_root: Path) -> Mapping[str, str]:
    payload = load_canonical_policy_payload(project_root / "AGENTS.md")
    phase1_docs = [str(item) for item in payload.get("repo_authorities", {}).get("phase1_docs", [])]
    classifications = [str(name) for name in payload.get("task_classifications", {}).keys()]
    skills_registry = payload.get("skills_registry", {})
    classification_list = "\n".join(f"- `{item}`" for item in classifications)
    skill_registry_bullets = "\n".join(f"- `{name}`" for name in sorted(skills_registry.keys()))
    invoke_skills_body = (
        "Canonical skill authority lives in:\n\n"
        "- `AGENTS.md`\n"
        "- `.agents/skills/*`\n\n"
        "Registry keys (`AGENTS.md` → `skills_registry`; each mirrors to `.cursor/skills/<skill-folder>/` per the `path` entry):\n\n"
        f"{skill_registry_bullets}\n\n"
        "Do not treat `.cursor/skills/*` as canonical.\n"
    )

    rules: dict[str, str] = {
        ".cursor/rules/phase1-governance-guardrails.mdc": _mdc(
            "Phase 1 Governance Guardrails",
            "Compatibility shim for canonical Phase 1 guardrails.",
            (
                "## Canonical documents\n\n"
                f"- `{phase1_docs[0]}`\n"
                f"- `{phase1_docs[1]}`\n"
                "- `AGENTS.md`\n\n"
                "## Mandatory pre-edit classification\n\n"
                "Before editing `Pipeline.py` or any Phase 1 logic, use the canonical classification set from `AGENTS.md`:\n\n"
                f"{classification_list}\n\n"
                "This shim exists so local Cursor workflows stay aligned with the runtime. If this file disagrees with `AGENTS.md`, `AGENTS.md` wins."
            ),
        ),
        ".cursor/rules/docs-must-match-runtime.mdc": _mdc(
            "Docs Must Match Runtime",
            "Compatibility shim that points local docs maintenance back to canonical sources.",
            dedent(
                """\
                Update canonical sources first:

                - `AGENTS.md`
                - `README.md`
                - Phase 1 docs under `docs/`

                Then rerender `.cursor` shims with `python tools/render_cursor_projection.py`.
                """
            ),
        ),
        ".cursor/rules/e-drive-artifacts.mdc": _mdc(
            "E Drive Artifacts",
            "Compatibility shim for the canonical E: drive artifact policy.",
            dedent(
                """\
                All pipeline artifacts remain on the E: drive under `E:\\stock_csvs_AI-Perspective`.

                Canonical path and resume semantics live in:

                - `README.md`
                - `AGENTS.md`
                - the runtime actions in `tools/control_plane.py`
                """
            ),
        ),
        ".cursor/rules/invoke-auditor-on-audit-request.mdc": _mdc(
            "Invoke Auditor On Audit Request",
            "Compatibility shim for the canonical auditor handoff.",
            dedent(
                """\
                Use the local `pipeline-auditor` alias only as a thin wrapper around the canonical `Auditor` role in `AGENTS.md`.
                """
            ),
        ),
        ".cursor/rules/invoke-skills-on-pipeline-tasks.mdc": _mdc(
            "Invoke Skills On Pipeline Tasks",
            "Compatibility shim for the canonical skills registry.",
            invoke_skills_body,
        ),
        ".cursor/rules/no-global-pytest.mdc": dedent(
            """\
            ---
            description: Forbid bare/global pytest entrypoints; require repo-local invocation.
            alwaysApply: true
            ---

            # No Global Pytest

            Do not use bare `pytest` as the canonical repo entrypoint.

            Allowed forms:

            - `.venv\\Scripts\\python.exe -m pytest ...`
            - `.venv/bin/python -m pytest ...`

            If a command or doc surface still uses bare `pytest`, fix it.
            """
        ),
        ".cursor/rules/invoke-verifier-after-edits.mdc": _mdc(
            "Invoke Verifier After Edits",
            "Compatibility shim for the canonical verifier-after-edits guardrail.",
            dedent(
                """\
                The runtime and `AGENTS.md` are authoritative for verifier triggering.
                Local Cursor flows should hand off to the `verifier` alias after sensitive edits and must not self-certify completion.
                """
            ),
        ),
        ".cursor/rules/invoke-watcher-on-pipeline-failure.mdc": _mdc(
            "Invoke Watcher On Pipeline Failure",
            "Compatibility shim for the canonical watcher handoff.",
            dedent(
                """\
                The runtime and `AGENTS.md` own failure recovery. Use the local `pipeline-watcher` alias only as a compatibility wrapper for the canonical `Watcher` role.
                """
            ),
        ),
        ".cursor/rules/output-and-resume-contract.mdc": _mdc(
            "Output And Resume Contract",
            "Compatibility shim for canonical output and resume semantics.",
            dedent(
                """\
                Output and resume authority lives in:

                - `README.md`
                - `AGENTS.md`
                - runtime actions `run_pipeline`, `resume_pipeline`, and `read_pipeline_log`
                """
            ),
        ),
        ".cursor/rules/pipeline-auditor-behavior.mdc": _mdc(
            "Pipeline Auditor Behavior",
            "Compatibility shim for the canonical auditor role.",
            "Use this local rule only to steer users toward the canonical `Auditor` role in `AGENTS.md`.",
        ),
        ".cursor/rules/pipeline-research-standards.mdc": _mdc(
            "Pipeline Research Standards",
            "Compatibility shim for canonical Phase 1 research standards.",
            dedent(
                """\
                Frozen research semantics remain in the Phase 1 docs and `AGENTS.md`.
                Do not let this local file redefine them.
                """
            ),
        ),
    }

    commands: dict[str, str] = {
        ".cursor/commands/phase1-change-check.md": (
            "# phase1-change-check\n\n"
            "This command is a local compatibility shim.\n"
            "Canonical behavior lives in `AGENTS.md` and `python tools/control_plane.py phase1-change-check`.\n\n"
            "Protected-path matching is slash-normalized so Windows and repo-relative paths classify the same way.\n\n"
            "Supported classifications:\n\n"
            f"{classification_list}\n\n"
            "Example:\n\n"
            "```powershell\n"
            ".\\.venv\\Scripts\\python.exe tools/control_plane.py phase1-change-check --classification policy_changing --justification \"Touches control_plane/orchestrator.py\" --expected-file control_plane/orchestrator.py\n"
            "```\n"
        ),
        ".cursor/commands/run-pipeline.md": (
            "# run-pipeline\n\n"
            "Local compatibility shim for canonical runtime actions:\n\n"
            "- `run_pipeline`\n"
            "- `resume_pipeline`\n"
            "- `read_pipeline_log`\n\n"
            "Use `README.md` and `AGENTS.md` for the authoritative run/recovery contract.\n"
        ),
        ".cursor/commands/run-tests.md": (
            "# run-tests\n\n"
            "Local compatibility shim for canonical runtime actions:\n\n"
            "- `run_tests_marker`\n"
            "- `run_tests_all`\n"
            "- `run_tests_scoped`\n"
            "- `phase1_sanity_check`\n\n"
            "Use the smallest correct tier, then let the verifier record the authoritative result.\n"
        ),
        ".cursor/commands/phase1-sanity-check.md": dedent(
            """\
            # phase1-sanity-check

            Local compatibility shim for the canonical `phase1_sanity_check` action in `AGENTS.md`.

            Required artifact surfaces:

            - `02_metrics/overall_metrics.json`
            - `02_metrics/fold_metrics.csv`
            - `02_metrics/threshold_candidate_diagnostics.csv`
            - `02_metrics/policy_daily_returns.csv`
            - `03_features/feature_validation_report.csv`
            - `04_strategies/best_strategy_summary.json`
            - `04_strategies/model_comparison_report.csv`
            - `04_strategies/position_ranking_audit.csv`
            - `04_strategies/strategy_scorecards.csv`
            - `05_reports/final_report.md`
            - `06_state/resume_state.json`

            Canonical path contract:

            - log: `{output_dir}/00_logs/pipeline.log`
            - resume: `{output_dir}/06_state/resume_state.json`
            """
        ),
        ".cursor/commands/audit-pipeline.md": dedent(
            """\
            # audit-pipeline

            Local compatibility shim for the canonical `Auditor` role in `AGENTS.md`.
            Use this as a convenience alias only; the runtime policy remains authoritative.
            """
        ),
        ".cursor/commands/build-feature-discovery-pipeline.md": dedent(
            """\
            # build-feature-discovery-pipeline

            Local compatibility shim for the canonical `Builder` role in `AGENTS.md`.
            Follow the current task scope and frozen Phase 1 docs; do not treat this command as a source of new requirements.
            """
        ),
    }

    agents: dict[str, str] = {
        ".cursor/agents/pipeline-builder.md": dedent(
            """\
            ---
            name: pipeline-builder
            ---

            This local alias maps to the canonical `Builder` role in `AGENTS.md`.
            Use it as a thin compatibility wrapper only.
            """
        ),
        ".cursor/agents/pipeline-watcher.md": dedent(
            """\
            ---
            name: pipeline-watcher
            ---

            This local alias maps to the canonical `Watcher` role in `AGENTS.md`.
            Operational recovery only.
            """
        ),
        ".cursor/agents/verifier.md": dedent(
            """\
            ---
            name: verifier
            ---

            This local alias maps to the canonical `Verifier` role in `AGENTS.md`.
            Verifier evidence is authoritative; builder claims are not.
            """
        ),
        ".cursor/agents/pipeline-auditor.md": dedent(
            """\
            ---
            name: pipeline-auditor
            ---

            This local alias maps to the canonical `Auditor` role in `AGENTS.md`.
            Read-only inspection only.
            """
        ),
        ".cursor/agents/pipeline-runner.md": dedent(
            """\
            ---
            name: pipeline-runner
            ---

            This local alias maps to the canonical `Runner` role in `AGENTS.md`.
            Use only repo-local commands and approved skills.
            Never self-certify completion; hand off to `verifier`.
            """
        ),
        ".cursor/agents/dependency-agent.md": dedent(
            """\
            ---
            name: dependency-agent
            ---

            This local alias maps to the canonical `DependencyAgent` role in `AGENTS.md`.
            Only propose or install dependencies allowed by policy.
            Every dependency change must be pinned, tested, and handed to `verifier`.
            """
        ),
    }

    skills: dict[str, str] = {}
    for skill_name, spec in skills_registry.items():
        skill_path = str(spec.get("path", ""))
        if not skill_path:
            continue
        projected_path = skill_path.replace(".agents/skills/", ".cursor/skills/")
        skills[projected_path] = dedent(
            f"""\
            ---
            name: {Path(projected_path).parent.name}
            description: Compatibility projection of the canonical `{skill_name}` skill registry entry from `AGENTS.md`.
            ---

            This local skill file is non-canonical.

            Canonical authority:

            - `AGENTS.md`
            - `.agents/skills/*`
            - the Phase 1 governance docs under `docs/`

            Local purpose:

            - `{spec.get("purpose", "Compatibility shim")}`
            """
        )

    projection = {}
    projection.update(rules)
    projection.update(commands)
    projection.update(agents)
    projection.update(skills)
    projection[".cursor/projection_manifest.json"] = (
        '{\n'
        '  "generated_by": "tools/render_cursor_projection.py",\n'
        '  "source_of_truth": "AGENTS.md",\n'
        '  "canonical_skill_root": ".agents/skills"\n'
        '}\n'
    )
    return projection


def render_cursor_projection(project_root: Path) -> list[Path]:
    created: list[Path] = []
    for relative_path, content in build_cursor_projection(project_root).items():
        target = project_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
        created.append(target)
    return created
