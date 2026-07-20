"""Commit message and git safety tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from todos_tool.commit_message import generate_commit_message, validate_commit_message
from todos_tool.errors import GitError
from todos_tool.git_service import refuse_if_dirty, stage_paths, status
from todos_tool.models import ItemType, TodoItem


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
    assert msg.startswith("feat:")
    assert len(msg) <= 72
    validate_commit_message(msg, _item())


def test_commit_message_bans_agent_words() -> None:
    with pytest.raises(GitError):
        validate_commit_message("feat: cursor agent todo attempt")


def test_dirty_tree_refused(git_project: Path) -> None:
    (git_project / "dirty.txt").write_text("x", encoding="utf-8")
    with pytest.raises(GitError):
        refuse_if_dirty(git_project, allow_dirty=False)


def test_todos_metadata_dirty_allowed(git_project: Path) -> None:
    todos_item = git_project / "todos" / "items" / "001.yaml"
    todos_item.parent.mkdir(parents=True)
    todos_item.write_text("id: x\n", encoding="utf-8")
    st = refuse_if_dirty(git_project, allow_dirty=False)
    assert st.is_dirty


def test_explicit_staging_only(git_project: Path) -> None:
    (git_project / "a.txt").write_text("a", encoding="utf-8")
    (git_project / "b.txt").write_text("b", encoding="utf-8")
    stage_paths(git_project, ["a.txt"])
    st = status(git_project)
    # a staged, b untracked
    assert "a.txt" in st.porcelain
    assert "b.txt" in st.porcelain
    assert "A  a.txt" in st.porcelain or "A  a.txt" in st.porcelain.replace("\n", " ")
