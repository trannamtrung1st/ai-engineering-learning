"""Consistency checks for bundled planning example agent_context."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.agent_context import (
    resolve_phase_agent_context,
    validate_agent_context_paths,
)
from top_down_planning.config_loader import merge_run_options
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal
from top_down_planning.prompts import build_render_batch_prompt, build_planning_prompt
from top_down_planning.scheduler import initialize_root_plan
from top_down_planning.models import SourceMetadata
from tests.helpers import planning_prompt_kwargs


def test_bundled_planning_example_agent_context() -> None:
    examples_root = Path(__file__).resolve().parents[2] / "examples"
    options = merge_run_options(
        config_path=examples_root / "planning.config.yaml",
        input_path=examples_root / "idea.md",
        output_dir=examples_root / "planning-output",
        output_goal_file=examples_root / "output-goal.md",
        workspace=examples_root,
    )
    planning = resolve_phase_agent_context("planning", options.agent_context)
    rendering = resolve_phase_agent_context("rendering", options.agent_context)
    review = resolve_phase_agent_context("review", options.agent_context)
    validate_agent_context_paths(examples_root, planning, label="planning")
    validate_agent_context_paths(examples_root, rendering, label="rendering")
    validate_agent_context_paths(examples_root, review, label="review")

    loaded = LoadedInput(path=examples_root / "idea.md", text="# idea", digest="x")
    goal = LoadedOutputGoal(text="plan", digest="g")
    plan = initialize_root_plan(
        source=SourceMetadata(
            input_file=str(examples_root / "idea.md"),
            output_goal="plan",
            input_digest="x",
            output_goal_digest="g",
        )
    )

    root = plan.plan[0]
    planning_prompt = build_planning_prompt(
        loaded_input=loaded,
        workspace=examples_root,
        output_goal=goal,
        plan=plan,
        selected_items=[root],
        embed_threshold=4000,
        agent_context=planning,
        **planning_prompt_kwargs(
            plan=plan,
            selected_items=[root],
            output_dir=examples_root / "planning-output",
        ),
    )
    render_prompt = build_render_batch_prompt(
        batch_id="batch-001",
        plan_digest="d" * 64,
        output_goal_digest=goal.digest,
        render_config_digest="c" * 64,
        batch_context_markdown="## Assigned items\n- `item-001` → `todo-item-001` → section 1\n",
        output_goal=goal,
        workspace=examples_root,
        embed_threshold=4000,
        agent_context=rendering,
    )

    assert "example-shared" in planning_prompt
    assert "example-planning" in planning_prompt
    assert "example-rendering" not in planning_prompt

    assert "example-shared" in render_prompt
    assert "example-rendering" in render_prompt
    assert "example-planning" not in render_prompt
