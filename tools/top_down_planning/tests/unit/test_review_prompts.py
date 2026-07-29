"""Tests for specialist review prompts."""

from __future__ import annotations

from pathlib import Path

from tests.helpers import render_output_goal
from top_down_planning.input_loader import load_markdown_input
from top_down_planning.models import ReviewCheckpoint, ReviewerRole
from top_down_planning.review_prompts import build_specialist_review_prompt
from tests.plan_factory import make_root_plan


def test_specialist_review_prompt_includes_required_context(example_input: Path) -> None:
    loaded = load_markdown_input(example_input)
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    prompt = build_specialist_review_prompt(
        loaded_input=loaded,
        workspace=example_input.parent,
        output_goal=loaded_goal,
        stop_hint=None,
        plan=plan,
        plan_digest="abc",
        embed_threshold=4000,
        reviewer_role=ReviewerRole.ADVERSARIAL,
        checkpoint=ReviewCheckpoint.FINAL_CANDIDATE,
    )
    assert "Specialist review session" in prompt
    assert "final_candidate" in prompt
    assert "specialist_review" in prompt
    assert "`abc`" in prompt
