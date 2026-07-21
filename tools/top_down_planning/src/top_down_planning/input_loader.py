"""Load the primary Markdown input and output goal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_file, digest_text
from top_down_planning.errors import PlanningToolError

_GOAL_SUFFIXES = {".md", ".markdown", ".txt"}


@dataclass(frozen=True)
class LoadedInput:
    path: Path
    text: str
    digest: str


@dataclass(frozen=True)
class LoadedOutputGoal:
    text: str
    digest: str
    path: Path | None = None

    @property
    def source_label(self) -> str:
        if self.path is not None:
            return str(self.path)
        return self.text


@dataclass(frozen=True)
class LoadedStopHint:
    text: str
    digest: str
    path: Path | None = None

    @property
    def source_label(self) -> str:
        if self.path is not None:
            return str(self.path)
        return self.text


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


def load_output_goal(
    *,
    inline: str | None = None,
    goal_file: Path | None = None,
) -> LoadedOutputGoal:
    if inline is not None and goal_file is not None:
        raise PlanningToolError("Use either --output-goal or --output-goal-file, not both")
    if goal_file is not None:
        resolved = goal_file.resolve()
        if not resolved.is_file():
            raise PlanningToolError(f"Output goal file not found: {goal_file}")
        if resolved.suffix.lower() not in _GOAL_SUFFIXES:
            raise PlanningToolError(
                "Output goal file must be .md, .markdown, or .txt: "
                f"{goal_file}"
            )
        text = resolved.read_text(encoding="utf-8")
        if not text.strip():
            raise PlanningToolError(f"Output goal file is empty: {goal_file}")
        return LoadedOutputGoal(text=text, digest=digest_file(resolved), path=resolved)
    if inline is not None:
        text = inline.strip()
        if not text:
            raise PlanningToolError("--output-goal must not be empty")
        return LoadedOutputGoal(text=text, digest=digest_text(text))
    raise PlanningToolError("Provide --output-goal or --output-goal-file")


def load_stop_hint(
    *,
    inline: str | None = None,
    hint_file: Path | None = None,
) -> LoadedStopHint | None:
    if inline is not None and hint_file is not None:
        raise PlanningToolError("Use either --stop-hint or --stop-hint-file, not both")
    if hint_file is not None:
        resolved = hint_file.resolve()
        if not resolved.is_file():
            raise PlanningToolError(f"Stop hint file not found: {hint_file}")
        if resolved.suffix.lower() not in _GOAL_SUFFIXES:
            raise PlanningToolError(
                "Stop hint file must be .md, .markdown, or .txt: "
                f"{hint_file}"
            )
        text = resolved.read_text(encoding="utf-8")
        if not text.strip():
            raise PlanningToolError(f"Stop hint file is empty: {hint_file}")
        return LoadedStopHint(text=text, digest=digest_file(resolved), path=resolved)
    if inline is not None:
        text = inline.strip()
        if not text:
            raise PlanningToolError("--stop-hint must not be empty")
        return LoadedStopHint(text=text, digest=digest_text(text))
    return None


def digest_output_goal(output_goal: str) -> str:
    """Backward-compatible helper for inline goal digests."""
    text = output_goal.strip()
    if not text:
        raise PlanningToolError("--output-goal must not be empty")
    return digest_text(text)
