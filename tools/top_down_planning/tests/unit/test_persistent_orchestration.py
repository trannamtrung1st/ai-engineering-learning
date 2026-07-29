import asyncio
from unittest.mock import patch

import pytest

from top_down_planning.cursor_client import SessionResult
from top_down_planning.digest import compute_plan_digest
from top_down_planning.input_loader import load_markdown_input
from top_down_planning.models import (
    MarkActionableOperation,
    PlanningLimits,
    PlanningMode,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    load_planning_state,
    new_run_state,
    save_plan,
    save_planning_state,
    save_run_state,
)
from top_down_planning.planning_state import new_planning_state
from top_down_planning.session_strategy import resolve_session_strategy
from tests.helpers import make_agent_response, render_output_goal
from tests.plan_factory import make_root_plan


@pytest.mark.asyncio
async def test_persistent_iteration_resumes_primary_chat(
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
    planning_state = new_planning_state()
    save_planning_state(output_dir, planning_state)
    plan_digest = compute_plan_digest(plan)
    strategy = resolve_session_strategy(None, planning_mode=PlanningMode.FULL)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        agent_bin=fake_agent_bin,
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

    resume_ids: list[str | None] = []

    async def fake_run_session(**kwargs):
        resume_ids.append(kwargs.get("resume_chat_id"))
        return SessionResult(exit_code=0, assistant_text="done", session_id="chat-123")

    response = make_agent_response(
        plan_digest=plan_digest,
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                title="Plan the requested work",
                objective="Produce the requested plan.",
                expected_outputs=["Plan"],
                acceptance_criteria=["Done when complete"],
            )
        ],
        selected_items=["item-001"],
    )

    with patch.object(orch.client, "run_session", side_effect=fake_run_session):
        with patch("top_down_planning.orchestrator.load_transaction", return_value=response):
            await orch._run_planning_iteration(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                eligible_items=[plan.plan[0]],
                planning_state=planning_state,
            )
            run_state.primary_chat_id = "chat-123"
            await orch._run_planning_iteration(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                eligible_items=[plan.plan[0]],
                planning_state=planning_state,
            )

    assert resume_ids[0] is None
    assert resume_ids[1] == "chat-123"


def test_planning_state_merge_persists_branch_status(tmp_path) -> None:
    from top_down_planning.models import BranchStatus, PlanningStateUpdate
    from top_down_planning.planning_state import merge_planning_state_update

    state = new_planning_state()
    updated = merge_planning_state_update(
        state,
        PlanningStateUpdate(
            branch_status=[
                BranchStatus(branch_id="item-001", status="refined", notes="ok")
            ]
        ),
    )
    save_planning_state(tmp_path, updated)
    loaded = load_planning_state(tmp_path)
    assert loaded is not None
    assert loaded.branch_status[0].branch_id == "item-001"


def test_simple_mode_disables_checkpoints() -> None:
    strategy = resolve_session_strategy(None, planning_mode=PlanningMode.SIMPLE)
    assert strategy.review_checkpoints == []
    assert strategy.final_adversarial_review is False
