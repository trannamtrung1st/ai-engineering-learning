from pathlib import Path

import pytest

from top_down_planning.digest import digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import digest_output_goal, load_markdown_input


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
