"""Load the primary Markdown input and output goal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_file, digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.models import PlanState

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


def resolve_output_goal_text(plan: PlanState) -> str:
    """Load the full output goal text from file when plan.yaml stores a reference."""
    return load_output_goal_from_plan(plan).text


def load_output_goal_from_plan(plan: PlanState) -> LoadedOutputGoal:
    """Rebuild the resolved output goal from canonical plan source metadata."""
    if plan.source.output_goal_file:
        path = Path(plan.source.output_goal_file)
        if not path.is_file():
            raise PlanningToolError(f"Output goal file not found: {path}")
        if path.suffix.lower() not in _GOAL_SUFFIXES:
            raise PlanningToolError(
                "Output goal file must be .md, .markdown, or .txt: "
                f"{path}"
            )
        resolved = path.resolve()
        text = resolved.read_text(encoding="utf-8")
        if not text.strip():
            raise PlanningToolError(f"Output goal file is empty: {path}")
        return LoadedOutputGoal(text=text, digest=digest_file(resolved), path=resolved)
    text = plan.source.output_goal.strip()
    if not text:
        raise PlanningToolError("Plan source output_goal is empty")
    digest = plan.source.output_goal_digest or digest_text(text)
    return LoadedOutputGoal(text=text, digest=digest)


def digest_output_goal(output_goal: str) -> str:
    """Compute SHA-256 digest for inline output goal text."""
    text = output_goal.strip()
    if not text:
        raise PlanningToolError("--output-goal must not be empty")
    return digest_text(text)


def normalize_persisted_text(text: str) -> str:
    """Collapse whitespace so plan.yaml source fields stay readable."""
    return " ".join(text.strip().split())


def persisted_goal_label(loaded: LoadedOutputGoal) -> str:
    """Return a compact label for plan.yaml when the goal may live in a file."""
    if loaded.path is not None:
        for line in loaded.text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:200]
        return loaded.path.name
    return normalize_persisted_text(loaded.text)


def persisted_stop_hint_label(loaded: LoadedStopHint) -> str:
    if loaded.path is not None:
        for line in loaded.text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:200]
        return loaded.path.name
    return normalize_persisted_text(loaded.text)


def build_source_metadata(
    *,
    input_file: str,
    input_digest: str,
    loaded_goal: LoadedOutputGoal,
    loaded_stop_hint: LoadedStopHint | None = None,
) -> "SourceMetadata":
    from top_down_planning.models import SourceMetadata

    stop_hint: str | None = None
    stop_hint_file: str | None = None
    stop_hint_digest: str | None = None
    if loaded_stop_hint is not None:
        stop_hint = persisted_stop_hint_label(loaded_stop_hint)
        stop_hint_file = (
            str(loaded_stop_hint.path) if loaded_stop_hint.path is not None else None
        )
        stop_hint_digest = loaded_stop_hint.digest

    return SourceMetadata(
        input_file=input_file,
        output_goal=persisted_goal_label(loaded_goal),
        output_goal_file=(
            str(loaded_goal.path) if loaded_goal.path is not None else None
        ),
        input_digest=input_digest,
        output_goal_digest=loaded_goal.digest,
        stop_hint=stop_hint,
        stop_hint_file=stop_hint_file,
        stop_hint_digest=stop_hint_digest,
    )
