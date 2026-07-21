"""Load the primary Markdown planning input."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_file, digest_text
from top_down_planning.errors import PlanningToolError


@dataclass(frozen=True)
class LoadedInput:
    path: Path
    text: str
    digest: str


def load_markdown_input(path: Path) -> LoadedInput:
    resolved = path.resolve()
    if not resolved.is_file():
        raise PlanningToolError(f"Input file not found: {path}")
    if resolved.suffix.lower() not in {".md", ".markdown"}:
        raise PlanningToolError(
            f"Input must be a Markdown file (.md or .markdown): {path}"
        )
    text = resolved.read_text(encoding="utf-8")
    if not text.strip():
        raise PlanningToolError(f"Input Markdown is empty: {path}")
    return LoadedInput(path=resolved, text=text, digest=digest_file(resolved))


def digest_output_goal(output_goal: str) -> str:
    goal = output_goal.strip()
    if not goal:
        raise PlanningToolError("--output-goal must not be empty")
    return digest_text(goal)
