"""Tests for aggregate vs work item kinds."""

from __future__ import annotations

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.production import ItemDispositionRecord, validate_batch_request
from top_down_planning.domain.readiness import compute_ready_view, resolve_satisfaction
from top_down_planning.domain.validators import validate_plan


def _plan_with_aggregate() -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
        outcome="Docs complete.",
    )
    concepts = PlanItem(
        id="item-concepts",
        parent_id="item-root",
        order_key="0000000000",
        title="Concepts",
        outcome="Concepts written.",
        kind="work",
    )
    architecture = PlanItem(
        id="item-architecture",
        parent_id="item-root",
        order_key="0000000100",
        title="Architecture",
        outcome="Architecture written.",
        kind="work",
        depends_on=["item-concepts"],
    )
    return Plan(
        id="plan-agg",
        revision=1,
        output_goal="Document the system.",
        items={
            "item-root": root,
            "item-concepts": concepts,
            "item-architecture": architecture,
        },
    )


def test_aggregate_never_in_ready_item_ids() -> None:
    view = compute_ready_view(_plan_with_aggregate())
    assert "item-root" not in view.ready_item_ids
    assert "item-concepts" in view.ready_item_ids
    assert "item-architecture" not in view.ready_item_ids


def test_aggregate_satisfaction_derived_from_descendants() -> None:
    plan = _plan_with_aggregate()
    assert resolve_satisfaction(plan, "item-root").state == "unresolved"
    dispositions = {
        "item-concepts": "completed",
        "item-architecture": "completed",
    }
    result = resolve_satisfaction(plan, "item-root", dispositions)
    assert result.state == "satisfied"
    assert result.source == "derived_subtree"


def test_work_items_remain_batchable() -> None:
    plan = _plan_with_aggregate()
    view = compute_ready_view(plan)
    issues = validate_batch_request(
        plan,
        plan_items=["item-concepts"],
        dispositions={
            "item-concepts": ItemDispositionRecord(disposition="completed"),
        },
        ready_item_ids=set(view.ready_item_ids),
        empty_output=True,
        empty_output_reason="n/a",
    )
    assert issues == []


def test_aggregate_disposition_rejected_in_batch() -> None:
    plan = _plan_with_aggregate()
    issues = validate_batch_request(
        plan,
        plan_items=["item-root"],
        dispositions={
            "item-root": ItemDispositionRecord(disposition="completed"),
        },
        ready_item_ids={"item-root"},
        empty_output=True,
        empty_output_reason="n/a",
    )
    assert any("aggregate" in issue for issue in issues)


def test_missing_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind is required"):
        PlanItem.from_dict(
            {
                "id": "item-a",
                "parent_id": None,
                "order_key": "0000000000",
                "title": "A",
            }
        )


def test_aggregate_without_descendants_warns() -> None:
    plan = Plan(
        id="plan-empty-agg",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )
    result = validate_plan(plan)
    assert any(issue.code == "aggregate_without_descendants" for issue in result.issues)


def test_mixed_tree_dependency_semantics() -> None:
    plan = _plan_with_aggregate()
    view = compute_ready_view(plan, {"item-concepts": "completed"})
    assert "item-architecture" in view.ready_item_ids
    assert "item-root" not in view.ready_item_ids
