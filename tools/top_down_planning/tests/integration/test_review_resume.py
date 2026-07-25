"""Resume behavior through review stages."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import FinalStatus, PlanningLimits, ReviewConfig, ReviewStatus
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import (
    final_confirmation_result_path,
    load_run_state,
    whole_plan_review_result_path,
)


@pytest.mark.asyncio
async def test_resume_reuses_whole_plan_review_and_runs_confirmation(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output"
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    limits = PlanningLimits(max_iterations=5, batch_size=2, concurrent_batches=1)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True),
    )
    first = await Orchestrator(config).run()
    assert first.review_status == ReviewStatus.CONFIRMED
    assert whole_plan_review_result_path(output_dir).is_file()
    assert final_confirmation_result_path(output_dir).is_file()

    final_confirmation_result_path(output_dir).unlink()
    run_state = load_run_state(output_dir)
    assert run_state is not None
    run_state.generated_artifacts = []
    from top_down_planning.persistence import save_run_state

    save_run_state(output_dir, run_state)
    artifact = output_dir / "implementation-plan.md"
    if artifact.is_file():
        artifact.unlink()

    second = await Orchestrator(
        RunConfig(
            input_path=example_input,
            output_goal=loaded_goal,
            output_dir=output_dir,
            workspace_root=tmp_path,
            limits=limits,
            resume=True,
            agent_bin=fake_agent_bin,
            skip_probe=True,
            review=ReviewConfig(enabled=True),
        )
    ).run()

    assert second.status == FinalStatus.COMPLETE
    assert second.review_status == ReviewStatus.CONFIRMED
    assert whole_plan_review_result_path(output_dir).is_file()
    assert final_confirmation_result_path(output_dir).is_file()
    assert len(second.artifacts) == 1
