"""Unit tests for domain plan tree and atomic mutations."""

from __future__ import annotations

import pytest

from top_down_planning.domain.errors import (
    DependencyCycleError,
    InvalidMutationError,
    RevisionConflictError,
)
from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits
from top_down_planning.domain.mutations import apply_operations
from top_down_planning.domain.plan_tree import (
    children_of,
    display_traversal,
    serialized_plan_items,
)


def _sample_plan() -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        kind="work",
    )
    return Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )


def test_serialized_plan_items_include_depth() -> None:
    plan = _sample_plan()

    payloads = serialized_plan_items(plan)

    assert [item["depth"] for item in payloads] == [0, 1, 1]
    assert list(payloads[0].keys())[:3] == ["id", "parent_id", "depth"]
    assert payloads[0]["id"] == "item-root"
    assert payloads[1]["id"] == "item-first"
    assert payloads[2]["id"] == "item-second"


def test_plan_from_dict_requires_item_depth() -> None:
    plan = _sample_plan()
    payload = plan.to_dict()
    del payload["items"][1]["depth"]

    with pytest.raises(ValueError, match="missing required field: depth"):
        Plan.from_dict(payload)


def test_plan_from_dict_rejects_stale_item_depth() -> None:
    plan = _sample_plan()
    payload = plan.to_dict()
    payload["items"][1]["depth"] = 9

    with pytest.raises(ValueError, match="does not match hierarchy depth"):
        Plan.from_dict(payload)


def test_add_sibling_after_preserves_order_under_parent() -> None:
    plan = _sample_plan()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "add_item",
                "temp_id": "item-middle",
                "parent_id": "item-root",
                "placement": {"after": "item-first"},
                "item": {"kind": "work", "title": "Middle"},
            }
        ],
    )

    sibling_ids = [item.id for item in children_of(result.plan, "item-root")]
    assert sibling_ids == ["item-first", result.id_map["item-middle"], "item-second"]
    assert display_traversal(result.plan) == [
        ("item-root", "1"),
        ("item-first", "1.1"),
        (result.id_map["item-middle"], "1.2"),
        ("item-second", "1.3"),
    ]


def test_move_subtree_rejects_descendant_parent() -> None:
    plan = _sample_plan()
    child = PlanItem(
        id="item-child",
        parent_id="item-first",
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    plan.items["item-child"] = child

    with pytest.raises(InvalidMutationError, match="descendants"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "move_subtree",
                    "item_id": "item-first",
                    "new_parent_id": "item-child",
                    "placement": {"last_child": True},
                }
            ],
        )


def test_stale_base_revision_fails_clearly() -> None:
    plan = _sample_plan()

    with pytest.raises(RevisionConflictError, match="revision conflict"):
        apply_operations(
            plan,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-first",
                    "patch": {"title": "Renamed"},
                }
            ],
        )


def test_temp_ids_resolve_within_transaction() -> None:
    plan = _sample_plan()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "add_item",
                "temp_id": "temp-api",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "API"},
            },
            {
                "op": "add_dependency",
                "item_id": "item-second",
                "depends_on": "temp-api",
            },
        ],
    )

    api_id = result.id_map["temp-api"]
    assert result.plan.items["item-second"].depends_on == [api_id]


def test_add_item_resolves_depends_on_temp_ids_in_same_transaction() -> None:
    plan = _sample_plan()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "add_item",
                "temp_id": "temp-api",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "API"},
            },
            {
                "op": "add_item",
                "temp_id": "temp-ui",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {
    "kind": "work",

                    "title": "UI",
                    "depends_on": ["temp-api"],
                },
            },
        ],
    )

    api_id = result.id_map["temp-api"]
    ui_id = result.id_map["temp-ui"]
    assert result.plan.items[ui_id].depends_on == [api_id]


def test_exceeding_max_depth_warns_without_rejecting() -> None:
    plan = Plan(
        id="plan-deep",
        revision=1,
        output_goal="Deep tree",
        items={
            "item-a": PlanItem("item-a", None, "0000000000", "A", kind="work"),
        },
    )
    current_parent = "item-a"
    for index in range(4):
        child_id = f"item-d{index}"
        plan.items[child_id] = PlanItem(
            child_id,
            current_parent,
            "0000000000",
            f"Depth {index}",
        kind="work",
        )
        current_parent = child_id

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "add_item",
                "parent_id": current_parent,
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "Too deep"},
            }
        ],
        limits=PlanningLimits(max_depth=3),
    )

    assert result.revision == 2
    assert any("exceeded_depth_limit" in warning for warning in result.warnings)
    assert len(result.warnings) == len(set(result.warnings))


def test_superseded_items_excluded_from_active_traversal() -> None:
    plan = _sample_plan()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "supersede_item",
                "item_id": "item-first",
                "temp_id": "item-first-v2",
                "replacement": {"kind": "work", "title": "First revised"},
            }
        ],
    )

    replacement_id = result.id_map["item-first-v2"]
    traversal_ids = [item_id for item_id, _ in display_traversal(result.plan)]
    assert "item-first" not in traversal_ids
    assert replacement_id in traversal_ids
    assert result.plan.items["item-first"].planning_status == "superseded"


def test_budget_warnings_are_not_duplicated() -> None:
    plan = _sample_plan()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "add_item",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "Another sibling"},
            }
        ],
        limits=PlanningLimits(max_expansion_per_item=2),
    )

    assert result.warnings.count("item-root: exceeded_expansion_limit") == 1


def test_dependency_cycle_rejects_transaction() -> None:
    plan = _sample_plan()
    plan.items["item-a"] = PlanItem("item-a", "item-root", "0000000200", "A", kind="work")
    plan.items["item-b"] = PlanItem("item-b", "item-root", "0000000300", "B", kind="work", depends_on=["item-a"])
    plan.items["item-c"] = PlanItem("item-c", "item-root", "0000000400", "C", kind="work", depends_on=["item-b"])

    with pytest.raises(DependencyCycleError):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "add_dependency",
                    "item_id": "item-a",
                    "depends_on": "item-c",
                }
            ],
        )


def test_add_item_rejects_missing_title() -> None:
    plan = _sample_plan()

    with pytest.raises(InvalidMutationError, match="item title is required"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "add_item",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {},
                }
            ],
        )


def test_supersede_item_rejects_missing_kind() -> None:
    plan = _sample_plan()

    with pytest.raises(InvalidMutationError, match="item kind is required"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "supersede_item",
                    "item_id": "item-first",
                    "temp_id": "item-first-v2",
                    "replacement": {"title": "First revised"},
                }
            ],
        )


def test_supersede_item_rejects_items_with_active_children() -> None:
    plan = _sample_plan()

    with pytest.raises(InvalidMutationError, match="no active children"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "supersede_item",
                    "item_id": "item-root",
                    "replacement": {"kind": "aggregate", "title": "Replacement root"},
                }
            ],
        )


def test_add_item_rejects_non_open_planning_status() -> None:
    plan = _sample_plan()

    with pytest.raises(InvalidMutationError, match="planning_status open"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "add_item",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "Bad", "planning_status": "removed"},
                }
            ],
        )


def test_update_item_rejects_unknown_patch_fields() -> None:
    plan = _sample_plan()

    with pytest.raises(InvalidMutationError, match="unsupported fields"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-first",
                    "patch": {"depends_on": ["item-root"]},
                }
            ],
        )


def test_remove_item_recompacts_sibling_order_keys() -> None:
    plan = _sample_plan()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[{"op": "remove_item", "item_id": "item-first"}],
        reviews=[],
    )

    assert result.plan.items["item-first"].planning_status == "removed"
    assert result.plan.items["item-second"].order_key == "0000000000"


def test_remove_item_requires_review_history_context() -> None:
    plan = _sample_plan()

    with pytest.raises(InvalidMutationError, match="requires review history context"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[{"op": "remove_item", "item_id": "item-first"}],
        )


def test_remove_item_rejects_items_with_review_history() -> None:
    plan = _sample_plan()
    reviews = [
        {
            "id": "review-focused-plan-01",
            "type": "focused_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "session-1",
            "target_revision": 1,
            "scope": {"kind": "focused_plan", "item_ids": ["item-first"]},
            "status": "approved",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "target_refs": ["item-first"],
                    "issue": "Too vague.",
                    "recommended_change": "Add detail.",
                    "status": "resolved",
                }
            ],
            "revision_cycles": 0,
        }
    ]

    with pytest.raises(InvalidMutationError, match="review history"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[{"op": "remove_item", "item_id": "item-first"}],
            reviews=reviews,
        )
