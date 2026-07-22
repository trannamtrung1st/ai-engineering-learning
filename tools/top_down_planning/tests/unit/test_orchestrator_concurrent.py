import asyncio
from unittest.mock import patch

import pytest

from top_down_planning.cursor_client import SessionResult
from top_down_planning.errors import CursorSessionError, PlanningToolError
from top_down_planning.input_loader import load_markdown_input, load_output_goal
from top_down_planning.models import PlanningLimits
from top_down_planning.orchestrator import Orchestrator, RunConfig, _BatchSessionResult, _BatchSpec
from top_down_planning.persistence import new_run_state


@pytest.mark.asyncio
async def test_run_batch_sessions_launches_all_tasks_in_parallel(
    tmp_path,
    example_input,
    fake_agent_bin,
) -> None:
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    limits = PlanningLimits(
        max_iterations=10,
        batch_size=1,
        concurrent_batches=3,
        max_retries=1,
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=tmp_path / "planning-output",
        workspace_root=tmp_path,
        limits=limits,
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
    )
    specs = [
        _BatchSpec(iteration=1, batch_index=0, items=[], selected_ids=["item-001"]),
        _BatchSpec(iteration=2, batch_index=1, items=[], selected_ids=["item-002"]),
        _BatchSpec(iteration=3, batch_index=2, items=[], selected_ids=["item-003"]),
    ]

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_execute(**kwargs):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return _BatchSessionResult(
            spec=kwargs["spec"],
            result=SessionResult(exit_code=0, assistant_text='{"operations":[]}'),
        )

    with patch.object(orch, "_execute_batch_session", side_effect=fake_execute):
        await orch._run_batch_sessions(
            loaded=loaded,
            plan=loaded,
            run_state=run_state,
            output_dir=config.output_dir,
            specs=specs,
            attempt=1,
            validation_feedback=None,
        )

    assert peak == 3


@pytest.mark.asyncio
async def test_failed_wave_does_not_mutate_plan(
    tmp_path,
    example_input,
    fake_agent_bin,
) -> None:
    from top_down_planning.models import PlanItem
    from top_down_planning.persistence import load_plan
    from tests.plan_factory import make_root_plan

    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    output_dir = tmp_path / "planning-output"
    limits = PlanningLimits(
        max_iterations=10,
        batch_size=1,
        concurrent_batches=2,
        max_retries=1,
    )
    plan = make_root_plan(
        input_file=str(example_input),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id=None,
            title="Parallel root",
            objective="parallel",
            depth=0,
            order=2,
        )
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
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
    )
    specs = [
        _BatchSpec(
            iteration=1,
            batch_index=0,
            items=[plan.plan[0]],
            selected_ids=["item-001"],
        ),
        _BatchSpec(
            iteration=2,
            batch_index=1,
            items=[plan.plan[1]],
            selected_ids=["item-002"],
        ),
    ]

    call_count = 0

    async def flaky_execute(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs["spec"].batch_index == 1:
            raise CursorSessionError("simulated batch failure", recoverable=True)
        from top_down_planning.cursor_client import SessionResult

        return _BatchSessionResult(
            spec=kwargs["spec"],
            result=SessionResult(
                exit_code=0,
                assistant_text=(
                    '{"operations":[{"type":"mark_actionable","node_id":"item-001",'
                    '"expected_outputs":["x"],"acceptance_criteria":["y"]}]}'
                ),
            ),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    from top_down_planning.persistence import save_plan

    save_plan(output_dir, plan)

    with patch.object(orch, "_execute_batch_session", side_effect=flaky_execute):
        with pytest.raises(PlanningToolError):
            await orch._run_planning_wave(
                loaded=loaded,
                plan=plan,
                run_state=run_state,
                output_dir=output_dir,
                specs=specs,
            )

    unchanged = load_plan(output_dir)
    assert unchanged is not None
    assert len(unchanged.plan) == 2
    assert unchanged.plan[0].decomposition_status.value == "needs_expansion"
    assert run_state.iteration == 0
