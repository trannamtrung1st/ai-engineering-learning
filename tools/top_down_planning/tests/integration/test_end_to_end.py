import asyncio
import json
from pathlib import Path

import pytest

from top_down_planning.input_loader import load_markdown_input, load_output_goal
from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    FinalStatus,
    PlanningLimits,
    ReviewConfig,
    ReviewStatus,
    RunActiveStatus,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import load_plan, load_run_state, new_run_state, save_plan, save_run_state
from top_down_planning.scheduler import initialize_root_plan
from tests.helpers import default_generation, make_agent_response
from tests.plan_factory import make_root_plan
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
        limits=PlanningLimits(max_iterations=5),
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert report.actionable_items >= 2
    assert len(report.artifacts) == 1
    assert (output_dir / ".planning-output" / "plan.yaml").is_file()
    assert (output_dir / ".planning-output" / "run-state.json").is_file()
    assert (output_dir / ".planning-output" / "render" / "manifest.yaml").is_file()
    assert not (output_dir / "plan.md").exists()
    artifact_path = output_dir / "implementation-plan.md"
    assert artifact_path.is_file()
    plan = load_plan(output_dir)
    assert plan is not None
    assert len(plan.plan) >= 3
    artifact = artifact_path.read_text(encoding="utf-8")
    assert "# Assembled deliverable" in artifact
    assert "Rendered content for" in artifact


@pytest.mark.asyncio
async def test_resume_after_partial_run(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output"
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    limits = PlanningLimits(max_iterations=5)

    plan = make_root_plan(
        input_file=str(loaded.path),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    plan = apply_response(
        plan,
        make_agent_response(
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
        generation=default_generation(),
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


@pytest.mark.asyncio
async def test_resume_after_limit_reached_with_increased_max_iterations(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output-limit-resume"
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    stored_limits = PlanningLimits(max_iterations=2)

    plan = make_root_plan(
        input_file=str(loaded.path),
        output_goal=loaded_goal.text,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
    )
    plan = apply_response(
        plan,
        make_agent_response(
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
    from top_down_planning.persistence import update_final_status

    update_final_status(
        plan,
        FinalStatus.INCOMPLETE_LIMIT_REACHED,
        "Planning stopped because a configured safety limit was reached.",
    )

    run_state = new_run_state(
        input_file=str(loaded.path),
        output_goal=loaded_goal.source_label,
        input_digest=loaded.digest,
        output_goal_digest=loaded_goal.digest,
        limits=stored_limits,
        generation=default_generation(),
    )
    run_state.iteration = 2
    run_state.active_status = RunActiveStatus.COMPLETED
    output_dir.mkdir(parents=True, exist_ok=True)
    save_plan(output_dir, plan)
    save_run_state(output_dir, run_state)

    report = await Orchestrator(
        RunConfig(
            input_path=example_input,
            output_goal=loaded_goal,
            output_dir=output_dir,
            workspace_root=tmp_path,
            limits=PlanningLimits(max_iterations=10),
            resume=True,
            agent_bin=fake_agent_bin,
            skip_probe=True,
        )
    ).run()

    assert report.status == FinalStatus.COMPLETE
    run_state = load_run_state(output_dir)
    assert run_state is not None
    assert run_state.limits.max_iterations == 10
    assert run_state.iteration > 2
    plan = load_plan(output_dir)
    assert plan is not None
    assert plan.result.status == FinalStatus.COMPLETE


@pytest.mark.asyncio
async def test_resume_after_child_limit_blocked_with_increased_max_children(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    import os

    output_dir = tmp_path / "planning-output-child-limit-resume"
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    blocked_response = json.dumps(
        {
            "assessment": {"plan_complete": False, "summary": "Blocked"},
            "operations": [
                {
                    "type": "mark_blocked",
                    "node_id": "item-001",
                    "reason": "Source requires at least 9 direct children under item-001",
                    "constraint_code": "max_children_exceeded",
                    "required_min_children": 9,
                }
            ],
        }
    )
    stored_limits = PlanningLimits(
        max_iterations=5,
        max_children_per_expansion=8,
    )
    first_config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=stored_limits,
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    os.environ["FAKE_AGENT_PLANNING_JSON"] = blocked_response
    os.environ["FAKE_AGENT_EXPAND_ROOT"] = "false"
    try:
        first_report = await Orchestrator(first_config).run()
    finally:
        os.environ.pop("FAKE_AGENT_PLANNING_JSON", None)
        os.environ.pop("FAKE_AGENT_EXPAND_ROOT", None)

    assert first_report.status == FinalStatus.INCOMPLETE_BLOCKED

    resume_report = await Orchestrator(
        RunConfig(
            input_path=example_input,
            output_goal=loaded_goal,
            output_dir=output_dir,
            workspace_root=tmp_path,
            limits=PlanningLimits(
                max_iterations=5,
                max_children_per_expansion=12,
            ),
            resume=True,
            agent_bin=fake_agent_bin,
            skip_probe=True,
        )
    ).run()

    assert resume_report.status == FinalStatus.COMPLETE
    run_state = load_run_state(output_dir)
    assert run_state is not None
    assert run_state.limits.max_children_per_expansion == 12
    plan = load_plan(output_dir)
    assert plan is not None
    assert plan.result.status == FinalStatus.COMPLETE
    root = plan.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status != DecompositionStatus.BLOCKED


@pytest.mark.asyncio
async def test_resume_does_not_reset_review_blocked_without_child_limit_change(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    import os

    output_dir = tmp_path / "planning-output-review-blocked-resume"
    loaded = load_markdown_input(example_input)
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    needs_revision = json.dumps(
        {
            "stage": "whole_plan_review",
            "plan_digest": "placeholder",
            "decision": "needs_revision",
            "summary": "Fix coverage",
            "findings": [
                {
                    "severity": "major",
                    "category": "coverage",
                    "node_ids": ["item-001"],
                    "description": "Reopen root",
                    "recommended_change": "Replan branch",
                }
            ],
        }
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=5),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True, max_revision_cycles=0),
    )
    os.environ["FAKE_AGENT_REVIEW_JSON"] = needs_revision
    try:
        first_report = await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_REVIEW_JSON", None)

    assert first_report.status == FinalStatus.INCOMPLETE_BLOCKED
    plan = load_plan(output_dir)
    assert plan is not None
    assert plan.result.review_status == ReviewStatus.NEEDS_REVISION

    resume_report = await Orchestrator(
        RunConfig(
            input_path=example_input,
            output_goal=loaded_goal,
            output_dir=output_dir,
            workspace_root=tmp_path,
            limits=PlanningLimits(max_iterations=5),
            resume=True,
            agent_bin=fake_agent_bin,
            skip_probe=True,
            review=ReviewConfig(enabled=True, max_revision_cycles=0),
        )
    ).run()

    assert resume_report.status == FinalStatus.INCOMPLETE_BLOCKED
    assert resume_report.review_status == ReviewStatus.NEEDS_REVISION


@pytest.mark.asyncio
async def test_end_to_end_with_concurrent_batches(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output-concurrent"
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(
            max_iterations=5,
        ),
        agent_bin=fake_agent_bin,
        skip_probe=True,
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert report.iterations >= 2
    iteration_dir = output_dir / ".planning-output" / "iterations"
    assert (iteration_dir / "001-response.json").is_file()
    assert (iteration_dir / "002-response.json").is_file()
