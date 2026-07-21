from __future__ import annotations

from top_down_planning.models import PlanState, SourceMetadata
from top_down_planning.scheduler import initialize_root_plan


def make_root_plan(
    *,
    input_file: str = "./idea.md",
    output_goal: str = "goal",
    input_digest: str = "a",
    output_goal_digest: str = "b",
    **kwargs: object,
) -> PlanState:
    source = SourceMetadata(
        input_file=input_file,
        output_goal=output_goal,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        **kwargs,
    )
    return initialize_root_plan(source=source)
