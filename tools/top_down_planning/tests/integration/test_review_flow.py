"""Integration tests for review gate and child-limit behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import render_output_goal
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
    assert not whole_plan_review_result_path(output_dir).is_file()


@pytest.mark.asyncio
async def test_child_limit_blocked_does_not_render(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    output_dir = tmp_path / "planning-output-blocked"
    loaded_goal = render_output_goal()
    blocked_response = json.dumps(
        {
            "operations": [
                {
                    "type": "mark_blocked",
                    "node_id": "item-001",
                    "title": "Plan the required top-level workstreams",
                    "objective": "Preserve all explicitly required sibling groups.",
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
        ),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True),
    )
    import os

    blocked_review = json.dumps(
        {
            "stage": "whole_plan_review",
            "plan_digest": "placeholder",
            "decision": "blocked",
            "summary": "Blocked items prevent rendering",
            "findings": [],
        }
    )
    os.environ["FAKE_AGENT_PLANNING_JSON"] = blocked_response
    os.environ["FAKE_AGENT_EXPAND_ROOT"] = "false"
    os.environ["FAKE_AGENT_REVIEW_JSON"] = blocked_review
    try:
        report = await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_PLANNING_JSON", None)
        os.environ.pop("FAKE_AGENT_EXPAND_ROOT", None)
        os.environ.pop("FAKE_AGENT_REVIEW_JSON", None)

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
    loaded_goal = render_output_goal()
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
                    "revision_mode": "reopen",
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


@pytest.mark.asyncio
async def test_amend_revision_cycle_completes_and_renders(
    tmp_path: Path,
    example_input: Path,
    fake_agent_bin: str,
) -> None:
    import os

    output_dir = tmp_path / "planning-output-amend-revision"
    loaded_goal = render_output_goal()
    review_sequence = json.dumps(
        [
            {
                "stage": "whole_plan_review",
                "plan_digest": "placeholder",
                "decision": "needs_revision",
                "summary": "Fix actionable leaf detail",
                "findings": [
                    {
                        "severity": "major",
                        "category": "consistency",
                        "revision_mode": "amend",
                        "node_ids": ["item-002", "item-003"],
                        "description": "Tighten acceptance criteria",
                        "recommended_change": "Tighten acceptance criteria and expected outputs",
                    }
                ],
            },
            {
                "stage": "whole_plan_review",
                "plan_digest": "placeholder",
                "decision": "approve",
                "summary": "Amendments look good",
                "findings": [],
            },
        ]
    )
    config = RunConfig(
        input_path=example_input,
        output_goal=loaded_goal,
        output_dir=output_dir,
        workspace_root=tmp_path,
        limits=PlanningLimits(max_iterations=8),
        agent_bin=fake_agent_bin,
        skip_probe=True,
        review=ReviewConfig(enabled=True, max_revision_cycles=1),
    )
    os.environ["FAKE_AGENT_REVIEW_SEQUENCE"] = review_sequence
    try:
        report = await Orchestrator(config).run()
    finally:
        os.environ.pop("FAKE_AGENT_REVIEW_SEQUENCE", None)

    assert report.status == FinalStatus.COMPLETE
    assert report.review_status == ReviewStatus.CONFIRMED
    assert len(report.artifacts) == 1

    plan = load_plan(output_dir)
    assert plan is not None
    for item_id in ("item-002", "item-003"):
        item = plan.item_by_id(item_id)
        assert item is not None
        assert any("Revised output" in value for value in item.expected_outputs)

    revision_audit = (
        output_dir / ".planning-output" / "reviews" / "revision-001.json"
    )
    assert revision_audit.is_file()
    revision_payload = json.loads(revision_audit.read_text(encoding="utf-8"))
    assert revision_payload["amend_node_ids"] == ["item-002", "item-003"]
    assert revision_payload["reopened_nodes"] == []

