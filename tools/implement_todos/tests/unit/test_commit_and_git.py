"""Commit message and git safety tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from todos_tool.commit_message import generate_commit_message, validate_commit_message
from todos_tool.errors import GitError
from todos_tool.git_finalize import finalize_worktree
from todos_tool.git_service import (
    filter_stageable_paths,
    head_sha,
    is_ignored_path,
    refuse_if_dirty,
    stage_paths,
    staged_paths,
    status,
)
from todos_tool.models import ItemType, ProvenanceKind, TodoItem


def _item(item_type: ItemType = ItemType.FEATURE) -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add account registration",
        type=item_type,
        description="desc",
        acceptance_criteria=["Registration endpoint is implemented."],
    )


def test_commit_message_prefix_and_length() -> None:
    msg = generate_commit_message(_item(), "src/auth.py | 10 +++++")
    assert msg.startswith("agent: feat:")
    assert len(msg) <= 72
    validate_commit_message(msg, _item())


def test_commit_message_bans_agent_words() -> None:
    with pytest.raises(GitError):
        validate_commit_message("feat: cursor agent todo attempt")


def test_dirty_tree_allowed_by_default(git_project: Path) -> None:
    (git_project / "dirty.txt").write_text("x", encoding="utf-8")
    st = refuse_if_dirty(git_project, allow_dirty=True)
    assert st.is_dirty


def test_finalize_includes_preexisting_dirty_changes(git_project: Path) -> None:
    baseline = head_sha(git_project)
    (git_project / "dirty.txt").write_text("preexisting\n", encoding="utf-8")
    (git_project / "tracked.txt").write_text("new\n", encoding="utf-8")

    result = finalize_worktree(
        git_project,
        commit_prefix="agent:",
        skip_commit=False,
        baseline_head=baseline,
    )

    assert result.provenance_kind == ProvenanceKind.DRIVER
    assert result.commit_sha != baseline


def test_explicit_staging_only(git_project: Path) -> None:
    (git_project / "a.txt").write_text("a", encoding="utf-8")
    (git_project / "b.txt").write_text("b", encoding="utf-8")
    stage_paths(git_project, ["a.txt"])
    st = status(git_project)
    # a staged, b untracked
    assert "a.txt" in st.porcelain
    assert "b.txt" in st.porcelain
    assert "A  a.txt" in st.porcelain or "A  a.txt" in st.porcelain.replace("\n", " ")


def test_filter_stageable_paths_skips_gitignored(git_project: Path) -> None:
    (git_project / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (git_project / "tracked.txt").write_text("ok", encoding="utf-8")
    ignored_dir = git_project / "ignored"
    ignored_dir.mkdir()
    (ignored_dir / "secret.txt").write_text("nope", encoding="utf-8")

    assert is_ignored_path(git_project, "ignored/secret.txt")
    assert not is_ignored_path(git_project, "tracked.txt")

    stageable = filter_stageable_paths(
        git_project,
        ["tracked.txt", "ignored/secret.txt"],
    )
    assert stageable == ["tracked.txt"]



def test_unrelated_unstaged_allowed_with_allow_dirty(git_project: Path) -> None:
    (git_project / "dirty.txt").write_text("x", encoding="utf-8")
    st = refuse_if_dirty(git_project, allow_dirty=True)
    assert st.is_dirty


def test_stage_paths_verifies_exact_set(git_project: Path) -> None:
    (git_project / "a.txt").write_text("a", encoding="utf-8")
    (git_project / "b.txt").write_text("b", encoding="utf-8")
    stage_paths(git_project, ["a.txt"])
    assert staged_paths(git_project) == ["a.txt"]
