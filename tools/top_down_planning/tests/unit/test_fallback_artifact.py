from top_down_planning.fallback_artifact import artifact_paths_from_output_goal


def test_artifact_paths_from_output_goal_section() -> None:
    goal = """# Goal

Produce an actionable implementation plan.

## Output artifacts

Write one Markdown deliverable:

- `implementation-plan.md`
"""
    assert artifact_paths_from_output_goal(goal) == ["implementation-plan.md"]
