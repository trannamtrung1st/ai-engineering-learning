"""Deterministic fallback deliverable when the render phase fails."""

from __future__ import annotations

import re
from pathlib import Path

from top_down_planning.artifact_writer import write_render_artifacts
from top_down_planning.models import PlanState, RenderArtifact, RenderResponse
from top_down_planning.renderer import render_plan_markdown


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


def default_artifact_filename(plan: PlanState) -> str:
    declared = artifact_paths_from_output_goal(plan.source.output_goal)
    if declared:
        return declared[0]
    first_line = plan.source.output_goal.strip().splitlines()[0]
    first_line = re.sub(r"^#+\s*", "", first_line).strip()
    slug = re.sub(r"[^\w\s-]", "", first_line.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return f"{slug or 'deliverable'}.md"


def write_fallback_artifact(output_dir: Path, plan: PlanState) -> Path:
    filename = default_artifact_filename(plan)
    response = RenderResponse(
        artifacts=[
            RenderArtifact(
                relative_path=filename,
                content=render_plan_markdown(plan),
            )
        ]
    )
    written = write_render_artifacts(output_dir, response)
    return written[0]
