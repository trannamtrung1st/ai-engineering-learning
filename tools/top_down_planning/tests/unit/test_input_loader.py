"""Load the primary Markdown input and output goal tests."""

from pathlib import Path

import pytest

from top_down_planning.digest import digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import (
    digest_output_goal,
    load_markdown_input,
    load_output_goal,
    load_stop_hint,
)


def test_load_markdown_input(example_input: Path) -> None:
    loaded = load_markdown_input(example_input)
    assert "CSV" in loaded.text
    assert len(loaded.digest) == 64


def test_digest_normalizes_newlines(tmp_path: Path) -> None:
    path = tmp_path / "input.md"
    path.write_text("hello\r\nworld", encoding="utf-8")
    loaded = load_markdown_input(path)
    assert loaded.digest == digest_text("hello\nworld")


def test_empty_output_goal_rejected() -> None:
    with pytest.raises(PlanningToolError):
        digest_output_goal("   ")


def test_missing_input_rejected(tmp_path: Path) -> None:
    with pytest.raises(PlanningToolError):
        load_markdown_input(tmp_path / "missing.md")


def test_load_output_goal_inline() -> None:
    loaded = load_output_goal(inline="Produce an actionable implementation plan")
    assert loaded.path is None
    assert "implementation plan" in loaded.text
    assert loaded.digest


def test_load_output_goal_from_file(tmp_path: Path) -> None:
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("# Goal\n\nProduce a migration plan.\n", encoding="utf-8")
    loaded = load_output_goal(goal_file=goal_file)
    assert loaded.path == goal_file.resolve()
    assert "migration plan" in loaded.text
    assert loaded.digest


def test_load_output_goal_rejects_both_sources() -> None:
    with pytest.raises(PlanningToolError):
        load_output_goal(inline="x", goal_file=Path("goal.md"))


def test_load_output_goal_requires_one_source() -> None:
    with pytest.raises(PlanningToolError):
        load_output_goal()


def test_load_stop_hint_inline() -> None:
    loaded = load_stop_hint(inline="Stop when each area has actionable leaves.")
    assert loaded is not None
    assert loaded.path is None
    assert "actionable leaves" in loaded.text


def test_load_stop_hint_from_file(tmp_path: Path) -> None:
    hint_file = tmp_path / "stop.md"
    hint_file.write_text("Stop after major workstreams are covered.\n", encoding="utf-8")
    loaded = load_stop_hint(hint_file=hint_file)
    assert loaded is not None
    assert loaded.path == hint_file.resolve()


def test_load_stop_hint_absent_by_default() -> None:
    assert load_stop_hint() is None


def test_load_stop_hint_rejects_both_sources() -> None:
    with pytest.raises(PlanningToolError):
        load_stop_hint(inline="x", hint_file=Path("stop.md"))
