from __future__ import annotations

from tools import verify_repo_authority


def test_git_deletion_ranges_prefers_merge_base_on_ci(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.delenv("GITHUB_EVENT_BEFORE", raising=False)

    def fake_ref_exists(ref: str) -> bool:
        return ref == "origin/main"

    def fake_git_lines(*args: str) -> list[str]:
        if args == ("merge-base", "HEAD", "origin/main"):
            return ["abc123"]
        return []

    monkeypatch.setattr(verify_repo_authority, "_git_ref_exists", fake_ref_exists)
    monkeypatch.setattr(verify_repo_authority, "_git_lines", fake_git_lines)

    assert verify_repo_authority._git_deletion_ranges() == ["abc123...HEAD"]


def test_git_deletions_include_committed_range_deletions(monkeypatch) -> None:
    monkeypatch.setattr(verify_repo_authority, "_git_deletion_ranges", lambda: ["base...HEAD"])

    def fake_deleted_paths(*diff_args: str) -> set[str]:
        if diff_args == ("base...HEAD",):
            return {"docs/obsolete.md"}
        return set()

    monkeypatch.setattr(verify_repo_authority, "_git_deleted_paths", fake_deleted_paths)

    assert verify_repo_authority._git_deletions() == ["docs/obsolete.md"]
