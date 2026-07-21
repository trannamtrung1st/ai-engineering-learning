import asyncio
from pathlib import Path

import pytest

from top_down_planning.input_loader import load_markdown_input, load_output_goal
from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    ExpandOperation,
    FinalStatus,
    PlanningLimits,
    RunActiveStatus,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import load_plan, load_run_state, new_run_state, save_plan, save_run_state
from top_down_planning.scheduler import initialize_root_plan
from top_down_planning.state_updates import apply_response


@pytest.mark.asyncio
async def test_end_to_end_with_fake_agent(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output"
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=5, batch_size=2),
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert report.actionable_items >= 2
    assert len(report.artifacts) == 1
    assert (output_dir / ".top-down-planning" / "plan.yaml").is_file()
    assert (output_dir / ".top-down-planning" / "run-state.json").is_file()
    assert not (output_dir / "plan.md").exists()
    artifact_path = output_dir / "implementation-plan.md"
    assert artifact_path.is_file()
    plan = load_plan(output_dir)
    assert plan is not None
    assert len(plan.plan) >= 3
    artifact = artifact_path.read_text(encoding="utf-8")
    assert "Rendered according to the output goal" in artifact
    assert "## Actionable items" in artifact


@pytest.mark.asyncio
async def test_resume_after_partial_run(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output"
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    limits = PlanningLimits(max_iterations=5, batch_size=2)

    plan = initialize_root_plan(
        input_file=str(loaded.path),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    plan = apply_response(
        plan,
        AgentResponse(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    children=[
                        ChildDraft(title="Area A", objective="A"),
                        ChildDraft(title="Area B", objective="B"),
                    ],
                )
            ]
        ),
    )
    run_state = new_run_state(
        input_file=str(loaded.path),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=limits,
    )
    run_state.iteration = 1
    run_state.active_status = RunActiveStatus.PAUSED
    output_dir.mkdir(parents=True, exist_ok=True)
    save_plan(output_dir, plan)
    save_run_state(output_dir, run_state)

    resume_config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=limits,
        resume=True,
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    report = await Orchestrator(resume_config).run()
    assert report.status == FinalStatus.COMPLETE
    run_state = load_run_state(output_dir)
    assert run_state is not None
    assert run_state.iteration >= 2
