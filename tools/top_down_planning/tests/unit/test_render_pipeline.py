"""Tests for sequential render pipeline and render-only mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import (
    DecompositionStatus,
    FinalStatus,
    PlanningLimits,
    RenderConfig,
    ReviewStatus,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    final_confirmation_result_path,
    load_plan,
    new_run_state,
    render_schedule_path,
    save_plan,
    save_run_state,
    whole_plan_review_result_path,
    write_json,
)
from top_down_planning.render_schedule import build_render_schedule, compute_schedule_digest
from top_down_planning.render_preconditions import validate_render_only_preconditions
from tests.helpers import default_generation, render_output_goal
from tests.plan_factory import make_root_plan


def test_schedule_includes_actionable_leaves_once(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        output_goal=loaded_goal.text,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan_digest = compute_plan_digest(plan)
    schedule, errors = build_render_schedule(
        plan,
        run_id="run-test",
        plan_digest=plan_digest,
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert errors == []
    assert len(schedule.batches) == 1
    assert schedule.batches[0].item_ids == ["item-001"]


def test_render_only_rejects_incomplete_plan(tmp_path: Path, example_input: Path) -> None:
    loaded_goal = load_output_goal(inline="goal")
    plan = make_root_plan(output_goal=loaded_goal.text, output_goal_digest=loaded_goal.digest)
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True)
    save_plan(output_dir, plan)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="in",
        output_goal_digest=loaded_goal.digest,
        limits=PlanningLimits(),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)
    with pytest.raises(PlanningToolError):
        validate_render_only_preconditions(
            output_dir,
            output_goal=loaded_goal,
            goal_overridden=False,
        )


@pytest.mark.asyncio
async def test_render_only_with_confirmed_plan(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "planning-output"
    loaded_goal = render_output_goal()
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="in",
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.result.review_status = ReviewStatus.CONFIRMED
    plan.result.status = FinalStatus.COMPLETE
    save_plan(output_dir, plan)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest="in",
        output_goal_digest=loaded_goal.digest,
        limits=PlanningLimits(max_iterations=5),
        generation=default_generation(),
    )
    save_run_state(output_dir, run_state)
    write_json(
        whole_plan_review_result_path(output_dir),
        {
            "stage": "whole_plan_review",
            "plan_digest": compute_plan_digest(plan),
            "decision": "approve",
            "summary": "ok",
            "findings": [],
        },
    )
    write_json(
        final_confirmation_result_path(output_dir),
        {
            "stage": "final_confirmation",
            "plan_digest": compute_plan_digest(plan),
            "decision": "confirmed",
            "summary": "ok",
            "findings": [],
        },
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=5),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        render_only=True,
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert (tmp_path / "implementation-plan.md").is_file()
    assert render_schedule_path(output_dir).is_file()
    schedule, _ = build_render_schedule(
        load_plan(output_dir),
        run_id="run-test",
        plan_digest=compute_plan_digest(load_plan(output_dir)),
        output_goal_digest=loaded_goal.digest,
        render_config=RenderConfig(),
    )
    assert compute_schedule_digest(schedule)
