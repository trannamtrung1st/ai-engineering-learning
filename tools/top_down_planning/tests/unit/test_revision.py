"""Tests for targeted branch revision."""

from __future__ import annotations

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState, SourceMetadata
from top_down_planning.revision import reopen_branch, revision_targets_from_findings
from top_down_planning.models import ReviewFinding, ReviewFindingCategory, ReviewFindingSeverity


def _expanded_plan() -> PlanState:
    return PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ),
        plan=[
            PlanItem(
                id="item-001",
                title="Root",
                objective="Root objective",
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Child",
                objective="Child objective",
                depth=1,
                order=2,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ],
    )


def test_reopen_branch_removes_descendants() -> None:
    plan = reopen_branch(_expanded_plan(), "item-001")
    assert [item.id for item in plan.plan] == ["item-001"]
    root = plan.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.NEEDS_EXPANSION


def test_revision_targets_collapse_descendants() -> None:
    plan = _expanded_plan()
    findings = [
        ReviewFinding(
            severity=ReviewFindingSeverity.MAJOR,
            category=ReviewFindingCategory.COVERAGE,
            node_ids=["item-001", "item-002"],
            description="Fix branch",
        )
    ]
    targets = revision_targets_from_findings(plan, findings)
    assert targets == ["item-001"]
