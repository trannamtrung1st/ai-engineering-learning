"""Integration tests for checkpoint review gate and structural expansion limits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import render_output_goal
from top_down_planning.checkpoint_flow import specialist_review_result_path
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import ValidationError
from top_down_planning.models import (
    FinalStatus,
    PlanningLimits,
    PlanningMode,
    ReviewConfig,
    ReviewStatus,
    ReviewerRole,
)
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import load_plan, planning_state_path


@pytest.mark.asyncio
async def test_review_artifacts_written_with_fake_agent(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output"
    loaded_goal = render_output_goal()
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=5),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True),
        planning_mode=PlanningMode.FULL,
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert report.review_status == ReviewStatus.CONFIRMED
    assert (output_dir / ".planning-output" / "review-state.json").is_file()
    assert planning_state_path(output_dir).is_file()
    plan = load_plan(output_dir)
    assert plan is not None
    digest = compute_plan_digest(plan)
    assert specialist_review_result_path(
        output_dir,
        role=ReviewerRole.ADVERSARIAL,
        plan_digest=digest,
    ).is_file()


@pytest.mark.asyncio
async def test_review_disabled_skips_review_artifacts_but_renders(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output-no-review"
    loaded_goal = render_output_goal()
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=5),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=False),
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert report.review_status == ReviewStatus.SKIPPED
    assert len(report.artifacts) == 1
    plan = load_plan(output_dir)
    assert plan is not None
    digest = compute_plan_digest(plan)
    assert not specialist_review_result_path(
        output_dir,
        role=ReviewerRole.ADVERSARIAL,
        plan_digest=digest,
    ).is_file()


@pytest.mark.asyncio
async def test_oversized_expand_fails_validation(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    import os

    output_dir = tmp_path / "planning-output-oversized-expand"
    loaded_goal = render_output_goal()
    too_many_children = [
        {"title": f"Child {index}", "objective": f"Do {index}"}
        for index in range(1, 10)
    ]
    oversized_expand = json.dumps(
        {
            "operations": [
                {
                    "type": "expand",
                    "node_id": "item-001",
                    "title": "Generated root",
                    "objective": "Describe the requested plan",
                    "children": too_many_children,
                }
            ],
        }
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(
            max_iterations=2,
            max_retries=1,
            max_children_per_expansion=3,
        ),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=False),
    )
    os.environ["FAKE_AGENT_PLANNING_JSON"] = oversized_expand
    os.environ["FAKE_AGENT_EXPAND_ROOT"] = "false"
    try:
        with pytest.raises(ValidationError) as exc_info:
            await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_PLANNING_JSON", None)
        os.environ.pop("FAKE_AGENT_EXPAND_ROOT", None)

    assert any("exceeds max children" in error for error in exc_info.value.errors)
    plan = load_plan(output_dir)
    assert plan is not None
    root = plan.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status.value == "needs_expansion"


@pytest.mark.asyncio
async def test_adversarial_blocked_review_blocks_without_render(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    import os

    output_dir = tmp_path / "planning-output-adversarial-blocked"
    loaded_goal = render_output_goal()
    blocked_review = json.dumps(
        {
            "stage": "specialist_review",
            "reviewer_role": "adversarial",
            "checkpoint": "final_candidate",
            "plan_digest": "placeholder",
            "decision": "blocked",
            "summary": "Coverage gaps remain",
            "findings": [],
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
        review=ReviewConfig(enabled=True),
        planning_mode=PlanningMode.FULL,
    )
    os.environ["FAKE_AGENT_SPECIALIST_JSON"] = blocked_review
    try:
        report = await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_SPECIALIST_JSON", None)

    assert report.review_status == ReviewStatus.BLOCKED
    assert report.status == FinalStatus.INCOMPLETE_BLOCKED
    assert report.artifacts == []
