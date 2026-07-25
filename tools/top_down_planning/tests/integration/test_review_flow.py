"""Integration tests for review gate and child-limit behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.input_loader import load_output_goal
from top_down_planning.models import (
    BlockedConstraintCode,
    FinalStatus,
    MarkBlockedOperation,
    PlanningLimits,
    ReviewConfig,
    ReviewStatus,
)
from top_down_planning.models import AgentResponse
from top_down_planning.orchestrator import Orchestrator, RunConfig
from top_down_planning.persistence import load_plan, whole_plan_review_result_path


@pytest.mark.asyncio
async def test_review_artifacts_written_with_fake_agent(
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
        review=ReviewConfig(enabled=True),
    )
    report = await Orchestrator(config).run()
    assert report.status == FinalStatus.COMPLETE
    assert report.review_status == ReviewStatus.CONFIRMED
    assert (output_dir / ".planning-output" / "review-state.json").is_file()
    assert whole_plan_review_result_path(output_dir).is_file()
    assert (
        output_dir / ".planning-output" / "reviews" / "whole-plan-request-prompt.md"
    ).is_file()


@pytest.mark.asyncio
async def test_review_disabled_skips_review_artifacts_but_renders(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output-no-review"
    loaded_goal = load_output_goal(inline="Produce an actionable implementation plan")
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
    assert not whole_plan_review_result_path(output_dir).is_file()


@pytest.mark.asyncio
async def test_child_limit_blocked_does_not_render(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output-blocked"
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
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(
            max_iterations=2,
            max_children_per_expansion=8,
        ),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True),
    )
    import os

    os.environ["FAKE_AGENT_PLANNING_JSON"] = blocked_response
    os.environ["FAKE_AGENT_EXPAND_ROOT"] = "false"
    try:
        report = await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_PLANNING_JSON", None)
        os.environ.pop("FAKE_AGENT_EXPAND_ROOT", None)

    assert report.status == FinalStatus.INCOMPLETE_BLOCKED
    assert report.review_status == ReviewStatus.BLOCKED
    assert report.artifacts == []
    plan = load_plan(output_dir)
    assert plan is not None
    root = plan.item_by_id("item-001")
    assert root is not None
    assert root.blocked_constraint_code == BlockedConstraintCode.MAX_CHILDREN_EXCEEDED


@pytest.mark.asyncio
async def test_needs_revision_with_zero_budget_blocks_without_render(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    import os

    output_dir = tmp_path / "planning-output-revision-budget"
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
        report = await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_REVIEW_JSON", None)

    assert report.review_status == ReviewStatus.NEEDS_REVISION
    assert report.status == FinalStatus.INCOMPLETE_BLOCKED
    assert report.artifacts == []

