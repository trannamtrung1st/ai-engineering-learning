import asyncio
from unittest.mock import patch

import pytest

from top_down_planning.cursor_client import SessionResult
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import CursorSessionError, PlanningToolError
from top_down_planning.input_loader import load_markdown_input
from top_down_planning.models import MarkActionableOperation, PlanningLimits
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import new_run_state, save_plan
from tests.helpers import default_generation, make_agent_response, render_output_goal
from tests.plan_factory import make_root_plan


@pytest.mark.asyncio
async def test_run_planning_iteration_issues_single_agent_session(
    tmp_path,
    example_input,
    fake_agent_bin,
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
    plan_digest = compute_plan_digest(plan)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        generation=default_generation(),
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    orch = Orchestrator(config)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
        generation=default_generation(),
    )
    session_calls = 0

    async def fake_run_session(**kwargs):
        nonlocal session_calls
        session_calls += 1
        return SessionResult(exit_code=0, assistant_text="done")

    response = make_agent_response(
        plan_digest=plan_digest,
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                title="Plan the requested work",
                objective="Produce the requested plan.",
                expected_outputs=["Plan"],
                acceptance_criteria=["Done"],
            )
        ],
        selected_items=["item-001"],
    )

    with patch.object(orch.client, "run_session", side_effect=fake_run_session):
        with patch("top_down_planning.orchestrator.load_transaction", return_value=response):
            updated = await orch._run_planning_iteration(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                eligible_items=[plan.plan[0]],
            )

    assert session_calls == 1
    assert updated.item_by_id("item-001") is not None
    assert run_state.iteration == 1


@pytest.mark.asyncio
async def test_failed_iteration_does_not_mutate_plan(
    tmp_path,
    example_input,
    fake_agent_bin,
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
    original_count = len(plan.plan)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        generation=default_generation(),
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    orch = Orchestrator(config)
    run_state = new_run_state(
        input_file=str(example_input),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
        generation=default_generation(),
    )

    async def fake_run_session(**kwargs):
        raise CursorSessionError("simulated session failure")

    with patch.object(orch.client, "run_session", side_effect=fake_run_session):
        with pytest.raises(PlanningToolError):
            await orch._run_planning_iteration(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                eligible_items=[plan.plan[0]],
            )

    assert len(plan.plan) == original_count
    assert run_state.iteration == 0
