"""Unit tests for deterministic plan validation."""

from __future__ import annotations

import pytest

from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits
from top_down_planning.domain.validators import validate_plan


def _chain_plan(depth: int) -> Plan:
    """Build an active chain of depth `depth` (root at depth 0)."""

    items: dict[str, PlanItem] = {}
    parent_id: str | None = None
    for level in range(depth + 1):
        item_id = f"item-{level}"
        items[item_id] = PlanItem(
            id=item_id,
            parent_id=parent_id,
            order_key="0000000000",
            title=f"Level {level}",
        )
        parent_id = item_id

    return Plan(
        id="plan-depth",
        revision=1,
        output_goal="Depth validation plan.",
        items=items,
    )


def test_approval_mode_fails_on_depth_overflow_draft_mode_warns() -> None:
    limits = PlanningLimits(max_depth=2)
    plan = _chain_plan(depth=3)

    draft = validate_plan(plan, limits=limits, mode="draft")
    assert draft.ok
    depth_issues = [issue for issue in draft.issues if issue.code == "exceeded_depth_limit"]
    assert len(depth_issues) == 1
    assert depth_issues[0].severity == "warning"
    assert depth_issues[0].path == ["item-3"]

    approval = validate_plan(plan, limits=limits, mode="approval")
    assert not approval.ok
    approval_depth = [issue for issue in approval.issues if issue.code == "exceeded_depth_limit"]
    assert len(approval_depth) == 1
    assert approval_depth[0].severity == "error"


def test_hierarchy_cycle_and_dependency_cycle_have_distinct_codes_and_paths() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root")
    first = PlanItem("item-first", "item-root", "0000000000", "First")
    second = PlanItem("item-second", "item-root", "0000000100", "Second")
    plan = Plan(
        id="plan-cycles",
        revision=1,
        output_goal="Cycle validation plan.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )

    plan.items["item-first"] = PlanItem(
        "item-first",
        "item-second",
        "0000000000",
        "First",
        depends_on=["item-second"],
    )
    plan.items["item-second"] = PlanItem(
        "item-second",
        "item-first",
        "0000000100",
        "Second",
        depends_on=["item-first"],
    )

    result = validate_plan(plan)
    codes = {issue.code for issue in result.issues}
    assert "hierarchy_cycle" in codes
    assert "dependency_cycle" in codes

    hierarchy = next(issue for issue in result.issues if issue.code == "hierarchy_cycle")
    dependency = next(issue for issue in result.issues if issue.code == "dependency_cycle")
    assert hierarchy.path == ["item-first", "item-second", "item-first"]
    assert dependency.path == ["item-first", "item-second", "item-first"]
    assert not result.ok


def test_orphan_parent_and_duplicate_item_id_are_reported() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root")
    orphan = PlanItem(
        "item-orphan",
        "item-missing",
        "0000000000",
        "Orphan",
    )
    duplicate = PlanItem("item-root", "item-root", "0000000100", "Duplicate key")
    plan = Plan(
        id="plan-orphan",
        revision=1,
        output_goal="Orphan validation plan.",
        items={
            "item-root": root,
            "item-orphan": orphan,
            "item-dup-key": duplicate,
        },
    )

    result = validate_plan(plan)
    codes = {issue.code for issue in result.issues}
    assert "missing_parent" in codes
    assert "duplicate_item_id" in codes
    assert not result.ok

    missing_parent = next(issue for issue in result.issues if issue.code == "missing_parent")
    assert missing_parent.path == ["item-orphan", "item-missing"]


def test_invalid_schema_version_fails_validation() -> None:
    plan = _chain_plan(depth=1)
    plan.schema_version = 99

    result = validate_plan(plan)

    assert not result.ok
    assert any(issue.code == "invalid_schema_version" for issue in result.issues)


def test_plan_from_dict_requires_schema_version() -> None:
    plan = _chain_plan(depth=1)

    with pytest.raises(ValueError, match="schema_version is required"):
        Plan.from_dict({key: value for key, value in plan.to_dict().items() if key != "schema_version"})
