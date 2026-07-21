"""Load the primary Markdown input and output goal tests."""

from pathlib import Path

import pytest

from top_down_planning.digest import digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import (
    build_source_metadata,
    digest_output_goal,
    load_markdown_input,
    load_output_goal,
    load_stop_hint,
    normalize_persisted_text,
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


def test_normalize_persisted_text_collapses_whitespace() -> None:
    text = "Stop expanding once.\n\nPrefer marking items actionable\nwhen sufficient."
    assert normalize_persisted_text(text) == (
        "Stop expanding once. Prefer marking items actionable when sufficient."
    )


def test_build_source_metadata_stores_file_reference(tmp_path: Path) -> None:
    goal_file = tmp_path / "planning-goal.md"
    goal_file.write_text(
        "Please use the ia-conventions skill.\n"
        "Based on the proposal, produce the todos list.\n",
        encoding="utf-8",
    )
    loaded_goal = load_output_goal(goal_file=goal_file)
    loaded_stop = load_stop_hint(
        inline="Stop expanding once each major workstream has actionable leaf tasks.\n"
        "Prefer marking items actionable over further expansion."
    )
    source = build_source_metadata(
        input_file=str(tmp_path / "proposal.md"),
        input_digest="input",
        loaded_goal=loaded_goal,
        loaded_stop_hint=loaded_stop,
    )
    assert source.output_goal == "Please use the ia-conventions skill."
    assert source.output_goal_file == str(goal_file.resolve())
    assert "\n" not in (source.stop_hint or "")
    assert source.stop_hint_file is None

