"""Resume behavior through checkpoint review stages."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import render_output_goal
from top_down_planning.checkpoint_flow import specialist_review_result_path
from top_down_planning.digest import compute_plan_digest
from top_down_planning.models import FinalStatus, PlanningLimits, PlanningMode, ReviewConfig, ReviewStatus, ReviewerRole
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import load_plan, load_run_state, save_run_state


@pytest.mark.asyncio
async def test_resume_reuses_specialist_reviews_and_reconfirms(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output"
    loaded_goal = render_output_goal()
    limits = PlanningLimits(max_iterations=5)
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True),
        planning_mode=PlanningMode.FULL,
    )
    first = await Orchestrator(config).run()
    assert first.review_status == ReviewStatus.CONFIRMED
    plan = load_plan(output_dir)
    assert plan is not None
    digest = compute_plan_digest(plan)
    adversarial_path = specialist_review_result_path(
        output_dir,
        role=ReviewerRole.ADVERSARIAL,
        plan_digest=digest,
    )
    assert adversarial_path.is_file()

    adversarial_path.unlink()
    run_state = load_run_state(output_dir)
    assert run_state is not None
    run_state.generated_artifacts = []
    save_run_state(output_dir, run_state)
    artifact = tmp_path / "implementation-plan.md"
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
    assert adversarial_path.is_file()
    assert len(second.artifacts) == 1
