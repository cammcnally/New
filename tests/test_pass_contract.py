from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tools.pass_contract import close_pass, start_pass
from tools.verify_pass_contract import collect_pre_commit_errors, collect_session_start_errors


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _commit_all(repo: Path, message: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config" / "canonical").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)

    for relative in (
        "config/canonical/repo_authority.yaml",
        "config/canonical/pass_contract_policy.json",
        "config/canonical/pass_contract_report_template.json",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((PROJECT_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")

    (repo / "docs" / "demo.md").write_text("original\n", encoding="utf-8")
    (repo / "docs" / "extra.md").write_text("extra\n", encoding="utf-8")

    _run_git(repo, "init")
    _run_git(repo, "add", ".")
    _commit_all(repo, "initial")
    return repo


def _load_report(repo: Path, issue_id: str) -> dict[str, object]:
    report_path = repo / ".local" / "pass_contract" / "issues" / issue_id / "pass_report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def _write_report(repo: Path, issue_id: str, payload: dict[str, object]) -> None:
    report_path = repo / ".local" / "pass_contract" / "issues" / issue_id / "pass_report.json"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_start_and_close_issue_records_go_history(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)

    start_pass(
        repo,
        issue_id="PASS-CONTRACT-001",
        objective="Update the demo document",
        planned_files=["docs/demo.md"],
        acceptance_criteria=["Document the demo change"],
        touches_protected_or_frozen=False,
    )

    (repo / "docs" / "demo.md").write_text("updated\n", encoding="utf-8")
    report = _load_report(repo, "PASS-CONTRACT-001")
    report["plain_english_diff_summary"] = ["Updated the demo document with the requested wording."]
    report["commands_run"] = ["uv run python tools/verify_pass_contract.py --policy-only"]
    report["command_results"] = [
        {
            "command": "uv run python tools/verify_pass_contract.py --policy-only",
            "exit_code": 0,
            "result": "pass",
            "stdout": "pass_contract_policy_ok",
            "stderr": "",
        }
    ]
    report["acceptance_criteria_results"] = [
        {
            "criterion": "Document the demo change",
            "satisfied": True,
            "evidence": "docs/demo.md contains the updated text.",
        }
    ]
    report["unresolved_items"] = []
    report["not_touched"] = ["docs/extra.md"]
    report["separate_approval_needed"] = []
    report["final_gate_decision"] = "GO FOR NEXT ISSUE"
    report["final_gate_reason"] = "The planned file changed, verification passed, and no extra scope drift occurred."
    _write_report(repo, "PASS-CONTRACT-001", report)

    close_pass(repo, issue_id="PASS-CONTRACT-001")

    closed_report = _load_report(repo, "PASS-CONTRACT-001")
    assert closed_report["report_status"] == "closed"
    assert closed_report["files_changed"] == ["docs/demo.md"]
    history_path = repo / ".local" / "pass_contract" / "history.jsonl"
    history_entries = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert history_entries[-1]["issue_id"] == "PASS-CONTRACT-001"
    assert history_entries[-1]["final_gate_decision"] == "GO FOR NEXT ISSUE"


def test_pre_commit_gate_blocks_staged_file_outside_planned_scope(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)

    start_pass(
        repo,
        issue_id="PASS-CONTRACT-002",
        objective="Only edit the demo document",
        planned_files=["docs/demo.md"],
        acceptance_criteria=["Update the demo document only"],
        touches_protected_or_frozen=False,
    )

    (repo / "docs" / "demo.md").write_text("demo update\n", encoding="utf-8")
    (repo / "docs" / "extra.md").write_text("extra update\n", encoding="utf-8")
    _run_git(repo, "add", "docs/demo.md", "docs/extra.md")

    errors = collect_pre_commit_errors(repo)
    assert any("staged files fall outside planned_files" in error for error in errors)


def test_session_start_blocks_after_stop_decision(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)

    start_pass(
        repo,
        issue_id="PASS-CONTRACT-003",
        objective="Stop cleanly after a failed verification attempt",
        planned_files=["docs/demo.md"],
        acceptance_criteria=["Capture the failed verification output"],
        touches_protected_or_frozen=False,
    )

    (repo / "docs" / "demo.md").write_text("needs follow-up\n", encoding="utf-8")
    report = _load_report(repo, "PASS-CONTRACT-003")
    report["plain_english_diff_summary"] = ["Documented the partial update and recorded the failed verification output."]
    report["commands_run"] = ["uv run python tools/verify_pass_contract.py --policy-only"]
    report["command_results"] = [
        {
            "command": "uv run python tools/verify_pass_contract.py --policy-only",
            "exit_code": 1,
            "result": "fail",
            "stdout": "",
            "stderr": "verification failed",
        }
    ]
    report["acceptance_criteria_results"] = [
        {
            "criterion": "Capture the failed verification output",
            "satisfied": False,
            "evidence": "The command result records the non-zero exit.",
        }
    ]
    report["unresolved_items"] = ["Verification still fails and requires follow-up."]
    report["not_touched"] = ["docs/extra.md"]
    report["separate_approval_needed"] = []
    report["final_gate_decision"] = "STOP"
    report["final_gate_reason"] = "The issue stopped cleanly because verification did not pass."
    _write_report(repo, "PASS-CONTRACT-003", report)

    close_pass(repo, issue_id="PASS-CONTRACT-003")

    errors = collect_session_start_errors(repo)
    assert errors == [
        "session-start blocked because the latest closed pass-contract report did not end with GO FOR NEXT ISSUE"
    ]
