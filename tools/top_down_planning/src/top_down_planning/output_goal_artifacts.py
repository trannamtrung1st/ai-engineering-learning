"""Output goal artifact parsing for render manifest and publication."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from top_down_planning.errors import PlanningToolError
from top_down_planning.models import PlanState
from top_down_planning.paths import validate_relative_path

_KNOWN_EXTENSIONS = {".md", ".yaml", ".yml", ".json", ".txt"}
_FALSE_POSITIVE_TOKENS = frozenset(
    {
        "HEAD",
        "complete",
        "confirmed",
        "pending",
        "blocked",
        "approve",
        "needs_rerender",
        "needs_revision",
    }
)


@dataclass(frozen=True)
class OutputGoalArtifacts:
    """Structured artifact metadata parsed from an output goal."""

    paths: list[str]
    deliverable_root: str | None
    final_paths: list[str]


def resolve_output_goal_text(plan: PlanState) -> str:
    """Load the full output goal text from file when plan.yaml stores a reference."""
    if plan.source.output_goal_file:
        path = Path(plan.source.output_goal_file)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return plan.source.output_goal


def parse_output_goal_artifacts(output_goal: str) -> OutputGoalArtifacts:
    """Parse the Output artifacts section into structured publication metadata."""
    raw_paths = _extract_raw_paths(output_goal)
    paths = [_validated_path(path) for path in raw_paths if _is_path_like(path)]
    if not paths:
        raise PlanningToolError(
            "Output goal must declare at least one artifact path under "
            "## Output artifacts."
        )
    deliverable_root = _resolve_deliverable_root(paths)
    final_paths = _final_paths(paths)
    return OutputGoalArtifacts(
        paths=paths,
        deliverable_root=deliverable_root,
        final_paths=final_paths,
    )


def _final_paths(paths: list[str]) -> list[str]:
    return sorted({path for path in paths if not path.endswith("/")})


def _validated_path(path: str) -> str:
    if path.endswith("/"):
        return validate_relative_path(path.rstrip("/"), label="artifact path") + "/"
    return validate_relative_path(path, label="artifact path")


def _extract_raw_paths(output_goal: str) -> list[str]:
    lines = output_goal.splitlines()
    in_section = False
    in_fence = False
    paths: list[str] = []
    fence_dir_prefix = ""

    for line in lines:
        if re.match(r"^#+\s*output artifacts\s*$", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r"^#+\s", line) and not line.strip().startswith("```"):
            break
        if not in_section:
            continue

        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            if not in_fence:
                fence_dir_prefix = ""
            continue

        if in_fence:
            candidate = stripped.split("#", 1)[0].strip().strip("`- ")
            if not candidate:
                continue
            if candidate.endswith("/"):
                fence_dir_prefix = candidate
                paths.append(candidate)
                continue
            if fence_dir_prefix and "/" not in candidate:
                paths.append(f"{fence_dir_prefix.rstrip('/')}/{candidate}")
            else:
                paths.append(candidate)
            continue

        if stripped.startswith("- `") or stripped.startswith("- `"):
            for match in re.finditer(r"`([^`]+)`", stripped):
                token = match.group(1).strip()
                if _looks_like_artifact_path(token):
                    paths.append(token)

    return paths


def _looks_like_artifact_path(token: str) -> bool:
    if not token or token in _FALSE_POSITIVE_TOKENS:
        return False
    if token.startswith("./scripts/"):
        return False
    suffix = PurePosixPath(token.split("#", 1)[0].strip()).suffix.lower()
    if suffix in _KNOWN_EXTENSIONS:
        return True
    if token.endswith("/"):
        return True
    return "/" in token and not token.startswith("http")


def _is_path_like(path: str) -> bool:
    token = path.strip()
    if not token or token in _FALSE_POSITIVE_TOKENS:
        return False
    if token.startswith("./scripts/"):
        return False
    suffix = PurePosixPath(token).suffix.lower()
    if suffix in _KNOWN_EXTENSIONS:
        return True
    if token.endswith("/"):
        return True
    return "/" in token


def _normalize_dir(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _resolve_deliverable_root(paths: list[str]) -> str | None:
    for path in paths:
        if path.endswith("/"):
            return _normalize_dir(path)

    parents: set[str] = set()
    for path in paths:
        parent = str(PurePosixPath(path).parent)
        if parent and parent != ".":
            parents.add(_normalize_dir(parent + "/"))

    if len(parents) > 1:
        raise PlanningToolError(
            "Output goal artifact paths resolve to multiple deliverable roots: "
            + ", ".join(sorted(parents))
        )
    if len(parents) == 1:
        return next(iter(parents))
    return None
