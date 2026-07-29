"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.digest import compute_plan_digest
from top_down_planning.generation_context import prepare_batch_context
from top_down_planning.input_loader import LoadedOutputGoal, load_output_goal
from top_down_planning.models import (
    AgentResponse,
    PlanItem,
    PlanState,
    PlanningLimits,
    ProcessedBatchRecord,
)

DEFAULT_PLAN_DIGEST = "a" * 64
DEFAULT_LIMITS = PlanningLimits()

STANDARD_RENDER_OUTPUT_GOAL = "Produce an actionable implementation plan."


def render_output_goal(text: str | None = None) -> LoadedOutputGoal:
    """Default output goal for render tests."""
    return load_output_goal(inline=text or STANDARD_RENDER_OUTPUT_GOAL)


def make_agent_response(**kwargs) -> AgentResponse:
    kwargs.setdefault("plan_digest", DEFAULT_PLAN_DIGEST)
    return AgentResponse(**kwargs)


def planning_prompt_kwargs(
    *,
    plan: PlanState,
    eligible_items: list[PlanItem],
    output_dir: Path,
    processed_batches: list[ProcessedBatchRecord] | None = None,
) -> dict[str, object]:
    digest = compute_plan_digest(plan)
    prepared = prepare_batch_context(
        plan=plan,
        selected_items=[],
        plan_digest=digest,
        output_dir=output_dir,
    )
    return {
        "plan_digest": digest,
        "batch_context_markdown": prepared.batch_context_markdown,
        "eligible_items": eligible_items,
        "processed_batches": processed_batches or [],
        "limits": DEFAULT_LIMITS,
    }
