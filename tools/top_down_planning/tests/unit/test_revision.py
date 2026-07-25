"""Tests for targeted branch revision."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    ReviewFinding,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    RevisionMode,
    SourceMetadata,
)
from top_down_planning.revision import (
    amend_targets_from_findings,
    apply_revision_from_findings,
    filter_amend_targets_after_reopen,
    reopen_branch,
    revision_targets_from_findings,
)


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
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Sibling",
                objective="Sibling objective",
                depth=1,
                order=3,
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


def test_revision_targets_collapse_descendants_for_reopen_only() -> None:
    plan = _expanded_plan()
    findings = [
        ReviewFinding(
            severity=ReviewFindingSeverity.MAJOR,
            category=ReviewFindingCategory.COVERAGE,
            revision_mode=RevisionMode.REOPEN,
            node_ids=["item-001", "item-002"],
            description="Fix branch",
        )
    ]
    targets = revision_targets_from_findings(plan, findings)
    assert targets == ["item-001"]


def test_amend_targets_keep_siblings_without_root_reopen() -> None:
    plan = _expanded_plan()
    findings = [
        ReviewFinding(
            severity=ReviewFindingSeverity.MAJOR,
            category=ReviewFindingCategory.CONSISTENCY,
            revision_mode=RevisionMode.AMEND,
            node_ids=["item-002", "item-003"],
            description="Fix sequencing",
        ),
        ReviewFinding(
            severity=ReviewFindingSeverity.MINOR,
            category=ReviewFindingCategory.OTHER,
            revision_mode=RevisionMode.ANNOTATE,
            node_ids=["item-001"],
            description="Stale note",
        ),
    ]
    assert amend_targets_from_findings(findings) == ["item-002", "item-003"]
    assert revision_targets_from_findings(plan, findings) == []


def test_apply_revision_annotates_without_reopening_siblings() -> None:
    plan = _expanded_plan()
    findings = [
        ReviewFinding(
            severity=ReviewFindingSeverity.MAJOR,
            category=ReviewFindingCategory.CONSISTENCY,
            revision_mode=RevisionMode.AMEND,
            node_ids=["item-002"],
            description="Fix cutover sequencing",
            recommended_change="Move loader hard-cut to item-008",
        ),
        ReviewFinding(
            severity=ReviewFindingSeverity.MINOR,
            category=ReviewFindingCategory.OTHER,
            revision_mode=RevisionMode.ANNOTATE,
            node_ids=["item-001"],
            description="Clear stale open question",
        ),
    ]
    result = apply_revision_from_findings(plan, findings)
    assert result.reopened_nodes == []
    assert result.amend_node_ids == ["item-002"]
    assert result.annotated_node_ids == ["item-001"]
    assert len(result.plan.plan) == 3
    root = result.plan.item_by_id("item-001")
    assert root is not None
    assert any("Clear stale open question" in note for note in root.notes)
    child = result.plan.item_by_id("item-002")
    assert child is not None
    assert child.decomposition_status == DecompositionStatus.ACTIONABLE


def test_filter_amend_targets_uses_pre_reopen_descendants() -> None:
    plan = _expanded_plan()
    reopened = reopen_branch(plan, "item-001")
    filtered = filter_amend_targets_after_reopen(
        pre_reopen_plan=plan,
        post_reopen_plan=reopened,
        amend_targets=["item-002", "item-003"],
        reopened_nodes=["item-001"],
    )
    assert filtered == []
