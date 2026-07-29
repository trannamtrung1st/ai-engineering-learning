"""Regression tests for disposition plan persistence."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_markdown_input
from top_down_planning.models import (
    CheckpointFinding,
    PlanningLimits,
    PlanningMode,
    ReviewCheckpoint,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    ReviewerRole,
    UpdateItemOperation,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    load_plan,
    new_run_state,
    save_plan,
    save_planning_state,
    save_run_state,
)
from top_down_planning.planning_state import new_planning_state
from top_down_planning.session_strategy import resolve_session_strategy
from top_down_planning.state_updates import apply_response
from tests.helpers import make_agent_response, render_output_goal
from tests.plan_factory import make_root_plan


@pytest.mark.asyncio
async def test_disposition_turn_returns_updated_plan(tmp_path, example_input) -> None:
    loaded = load_markdown_input(example_input)
    loaded_goal = render_output_goal()
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir(parents=True)
    limits = PlanningLimits(max_iterations=10, max_retries=1)
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    save_plan(output_dir, plan)
    planning_state = new_planning_state()
    save_planning_state(output_dir, planning_state)
    strategy = resolve_session_strategy(None, planning_mode=PlanningMode.FULL)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        skip_probe=True,
        planning_mode=PlanningMode.FULL,
        session_strategy=strategy,
    )
    orch = Orchestrator(config)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
    )
    run_state.session_strategy = strategy
    run_state.resolved_planning_mode = PlanningMode.FULL
    save_run_state(output_dir, run_state)

    plan_digest = compute_plan_digest(plan)
    response = make_agent_response(
        plan_digest=plan_digest,
        updates=[
            UpdateItemOperation(
                node_id="item-001",
                reason="Apply adversarial remediation.",
                notes=["Disposition remediation applied."],
            )
        ],
    )
    expected_plan = apply_response(plan, response)

    async def fake_iteration(**kwargs):
        updated = apply_response(kwargs["plan"], response)
        save_plan(output_dir, updated)
        run_state.iteration += 1
        return updated

    findings = [
        CheckpointFinding(
            id="adv-001",
            severity=ReviewFindingSeverity.MAJOR,
            category=ReviewFindingCategory.CONSISTENCY,
            reviewer_role=ReviewerRole.ADVERSARIAL,
            affected_branches=["item-001"],
            observation="Fix item-001 notes.",
            checkpoint=ReviewCheckpoint.FINAL_CANDIDATE,
        )
    ]

    with patch.object(orch, "_run_planning_iteration", side_effect=fake_iteration):
        returned_plan, _planning_state = await orch._run_disposition_turn(
            loaded=loaded,
            plan=plan,
            planning_state=planning_state,
            findings=findings,
            checkpoint=ReviewCheckpoint.FINAL_CANDIDATE,
            run_state=run_state,
            output_dir=output_dir,
        )

    assert compute_plan_digest(returned_plan) == compute_plan_digest(expected_plan)
    assert returned_plan.item_by_id("item-001").notes == [
        "Disposition remediation applied."
    ]


@pytest.mark.asyncio
async def test_decomposition_loop_preserves_disposition_plan_on_disk(
    tmp_path,
    example_input,
) -> None:
    loaded = load_markdown_input(example_input)
    loaded_goal = render_output_goal()
    output_dir = tmp_path / "planning-output"
    output_dir.mkdir(parents=True)
    limits = PlanningLimits(max_iterations=10, max_retries=1)
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    save_plan(output_dir, plan)
    planning_state = new_planning_state()
    save_planning_state(output_dir, planning_state)
    strategy = resolve_session_strategy(None, planning_mode=PlanningMode.FULL)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        skip_probe=True,
        planning_mode=PlanningMode.FULL,
        session_strategy=strategy,
    )
    orch = Orchestrator(config)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
    )
    run_state.session_strategy = strategy
    run_state.resolved_planning_mode = PlanningMode.FULL
    save_run_state(output_dir, run_state)

    plan_digest = compute_plan_digest(plan)
    response = make_agent_response(
        plan_digest=plan_digest,
        updates=[
            UpdateItemOperation(
                node_id="item-001",
                reason="Apply adversarial remediation.",
                notes=["Persisted by disposition iteration."],
            )
        ],
    )
    remediated_plan = apply_response(plan, response)
    save_plan(output_dir, remediated_plan)

    with patch(
        "top_down_planning.orchestrator.expandable_items",
        return_value=[],
    ):
        final_plan, _run_state = await orch._decomposition_loop(
            loaded=loaded,
            plan=plan,
            run_state=run_state,
            output_dir=output_dir,
            planning_state=planning_state,
        )

    on_disk = load_plan(output_dir)
    assert on_disk is not None
    assert compute_plan_digest(on_disk) == compute_plan_digest(remediated_plan)
    assert final_plan.item_by_id("item-001").notes == [
        "Persisted by disposition iteration."
    ]
