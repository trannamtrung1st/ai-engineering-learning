"""Output goal parsing helpers shared by render manifest and CLI."""

from __future__ import annotations

import re
from pathlib import Path

from top_down_planning.models import PlanState


def resolve_output_goal_text(plan: PlanState) -> str:
    """Load the full output goal text from file when plan.yaml stores a reference."""
    if plan.source.output_goal_file:
        path = Path(plan.source.output_goal_file)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return plan.source.output_goal


def artifact_paths_from_output_goal(output_goal: str) -> list[str]:
    lines = output_goal.splitlines()
    in_section = False
    paths: list[str] = []
    for line in lines:
        if re.match(r"^#+\s*output artifacts\s*$", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r"^#+\s", line):
            break
        if in_section:
            match = re.search(r"`([^`]+)`", line)
            if match:
                paths.append(match.group(1).strip())
    return paths
