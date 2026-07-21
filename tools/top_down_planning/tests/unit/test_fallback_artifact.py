from top_down_planning.fallback_artifact import (
    artifact_paths_from_output_goal,
    default_artifact_filename,
)
from top_down_planning.scheduler import initialize_root_plan


def test_artifact_paths_from_output_goal_section() -> None:
    goal = """# Goal

Produce an actionable implementation plan.

## Output artifacts

Write one Markdown deliverable:

- `implementation-plan.md`
"""
    assert artifact_paths_from_output_goal(goal) == ["implementation-plan.md"]


def test_default_artifact_filename_prefers_output_artifacts_section() -> None:
    goal = """Produce an actionable implementation plan.

## Output artifacts

- `implementation-plan.md`
"""
    plan = initialize_root_plan(
        input_file="./idea.md",
        output_goal=goal,
        input_digest="a",
        output_goal_digest="b",
    )
    assert default_artifact_filename(plan) == "implementation-plan.md"
