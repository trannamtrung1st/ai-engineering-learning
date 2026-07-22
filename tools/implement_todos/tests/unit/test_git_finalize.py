"""Tests for whole-worktree finalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from todos_tool.errors import GitError
from todos_tool.git_finalize import finalize_worktree
from todos_tool.git_service import head_sha, stage_paths
from todos_tool.models import ProvenanceKind


def test_finalize_stages_and_commits_all_changes(git_project: Path) -> None:
    baseline = head_sha(git_project)
    (git_project / "feature.txt").write_text("new\n", encoding="utf-8")
    (git_project / "prestaged.txt").write_text("staged\n", encoding="utf-8")
    stage_paths(git_project, ["prestaged.txt"])

    result = finalize_worktree(
        git_project,
        commit_prefix="agent:",
        skip_commit=False,
        baseline_head=baseline,
    )

    assert result.provenance_kind == ProvenanceKind.DRIVER
    assert result.commit_sha
    assert result.commit_sha != baseline
    assert (git_project / "feature.txt").is_file()


def test_finalize_external_provenance_when_head_advanced(git_project: Path) -> None:
    baseline = head_sha(git_project)
    (git_project / "manual.txt").write_text("manual\n", encoding="utf-8")
    stage_paths(git_project, ["manual.txt"])
    from todos_tool.git_service import commit

    commit(git_project, "agent: manual commit")

    result = finalize_worktree(
        git_project,
        commit_prefix="agent:",
        skip_commit=False,
        baseline_head=baseline,
    )

    assert result.provenance_kind == ProvenanceKind.EXTERNAL
    assert result.commit_sha == head_sha(git_project)


def test_finalize_clean_unchanged_head_fails(git_project: Path) -> None:
    baseline = head_sha(git_project)
    with pytest.raises(GitError, match="no commit provenance"):
        finalize_worktree(
            git_project,
            commit_prefix="agent:",
            skip_commit=False,
            baseline_head=baseline,
        )


def test_skip_commit_records_skipped_provenance(git_project: Path) -> None:
    baseline = head_sha(git_project)
    (git_project / "dirty.txt").write_text("x\n", encoding="utf-8")

    result = finalize_worktree(
        git_project,
        commit_prefix="agent:",
        skip_commit=True,
        baseline_head=baseline,
    )

    assert result.provenance_kind == ProvenanceKind.SKIPPED
    assert result.commit_sha == baseline


def test_finalize_uses_proposed_commit_message(git_project: Path) -> None:
    baseline = head_sha(git_project)
    (git_project / "feature.txt").write_text("new\n", encoding="utf-8")

    result = finalize_worktree(
        git_project,
        commit_prefix="agent:",
        skip_commit=False,
        baseline_head=baseline,
        commit_message="agent: feat: add feature",
    )

    assert result.provenance_kind == ProvenanceKind.DRIVER
    assert "agent: feat: add feature" in result.message
