"""Tests for review prompt content."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import DecompositionStatus, PlanItem, PlanState, SourceMetadata
from top_down_planning.review_prompts import build_whole_plan_review_prompt
from top_down_planning.render_brief import build_render_brief


def test_whole_plan_review_prompt_includes_required_context() -> None:
    plan = PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="Produce a plan",
            input_digest="input-digest",
            output_goal_digest="goal-digest",
            stop_hint="Stop at actionable leaves",
            stop_hint_digest="stop-digest",
        ),
        plan=[
            PlanItem(
                id="item-001",
                title="Root",
                objective="Root objective",
                decomposition_status=DecompositionStatus.ACTIONABLE,
            )
        ],
    )
    digest = "abc123digest"
    prompt = build_whole_plan_review_prompt(
        loaded_input=LoadedInput(path=Path("idea.md"), text="# Idea", digest="input-digest"),
        workspace=Path("."),
        output_goal=LoadedOutputGoal(text="Produce a plan", digest="goal-digest"),
        stop_hint=LoadedStopHint(text="Stop at actionable leaves", digest="stop-digest"),
        plan=plan,
        plan_digest=digest,
        embed_threshold=4000,
    )
    brief = build_render_brief(plan)

    assert "## Output goal" in prompt
    assert "Stop at actionable leaves" in prompt
    assert digest in prompt
    assert brief.strip() in prompt
    assert "# Idea" in prompt
    assert "Do not modify `plan.yaml`" in prompt
    assert "planning-review-tool" in prompt
