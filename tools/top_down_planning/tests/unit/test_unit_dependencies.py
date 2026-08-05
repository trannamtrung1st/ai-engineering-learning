"""Unit dependency graph derived from approved plan item dependencies."""

from __future__ import annotations

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_units import SubTdpUnit, derive_sub_tdp_units
from top_down_planning.domain.unit_dependencies import (
    UnitDependencyCycleError,
    classify_item_dependencies,
    derive_unit_dependencies,
    detect_unit_dependency_cycles,
)


def _item(
    item_id: str,
    *,
    parent_id: str | None,
    order_key: str,
    title: str,
    depends_on: list[str] | None = None,
    kind: str = "work",
) -> PlanItem:
    return PlanItem(
        id=item_id,
        parent_id=parent_id,
        order_key=order_key,
        title=title,
        outcome=f"{title} outcome.",
        kind=kind,
        depends_on=list(depends_on or []),
        scope=Scope(includes=[title.lower()]),
    )


def _root() -> PlanItem:
    return _item(
        PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        kind="aggregate",
    )


def test_independent_units_have_no_dependencies() -> None:
    plan = Plan(
        id="plan-indep",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item("item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A"),
            "item-b": _item("item-b", parent_id=PLAN_ROOT_ITEM_ID, order_key="2", title="B"),
        },
    )
    units = derive_sub_tdp_units(plan)
    deps = derive_unit_dependencies(plan, units)
    assert deps["item-a"] == []
    assert deps["item-b"] == []


def test_a_depends_on_b_creates_unit_edge() -> None:
    plan = Plan(
        id="plan-ab",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                depends_on=["item-b"],
            ),
            "item-b": _item("item-b", parent_id=PLAN_ROOT_ITEM_ID, order_key="2", title="B"),
        },
    )
    units = derive_sub_tdp_units(plan)
    deps = derive_unit_dependencies(plan, units)
    assert deps["item-a"] == ["item-b"]
    assert deps["item-b"] == []


def test_a_and_b_depend_on_c() -> None:
    plan = Plan(
        id="plan-abc",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                depends_on=["item-c"],
            ),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
                depends_on=["item-c"],
            ),
            "item-c": _item("item-c", parent_id=PLAN_ROOT_ITEM_ID, order_key="3", title="C"),
        },
    )
    units = derive_sub_tdp_units(plan)
    deps = derive_unit_dependencies(plan, units)
    assert deps["item-a"] == ["item-c"]
    assert deps["item-b"] == ["item-c"]
    assert deps["item-c"] == []


def test_descendant_cross_unit_dependency() -> None:
    """Item inside unit A depending on descendant of unit B creates A→B edge."""

    plan = Plan(
        id="plan-cross",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                kind="aggregate",
            ),
            "item-a-work": _item(
                "item-a-work",
                parent_id="item-a",
                order_key="1",
                title="A work",
                depends_on=["item-b-leaf"],
            ),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
                kind="aggregate",
            ),
            "item-b-leaf": _item(
                "item-b-leaf",
                parent_id="item-b",
                order_key="1",
                title="B leaf",
            ),
        },
    )
    units = derive_sub_tdp_units(plan)
    deps = derive_unit_dependencies(plan, units)
    assert deps["item-a"] == ["item-b"]
    assert deps["item-b"] == []


def test_unit_dependency_cycle_is_detected() -> None:
    plan = Plan(
        id="plan-cycle",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                depends_on=["item-b"],
            ),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
                depends_on=["item-a"],
            ),
        },
    )
    units = derive_sub_tdp_units(plan)
    deps = derive_unit_dependencies(plan, units)
    with pytest.raises(UnitDependencyCycleError):
        detect_unit_dependency_cycles(deps)


def test_aggregate_dependency_satisfied_via_descendant_owner() -> None:
    """Depending on an aggregate whose descendants live in another unit."""

    plan = Plan(
        id="plan-agg",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                depends_on=["item-b"],
            ),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
                kind="aggregate",
            ),
            "item-b-leaf": _item(
                "item-b-leaf",
                parent_id="item-b",
                order_key="1",
                title="B leaf",
            ),
        },
    )
    units = derive_sub_tdp_units(plan)
    deps = derive_unit_dependencies(plan, units)
    assert deps["item-a"] == ["item-b"]


def test_classify_item_dependencies_internal_vs_external() -> None:
    plan = Plan(
        id="plan-class",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                kind="aggregate",
            ),
            "item-a1": _item(
                "item-a1",
                parent_id="item-a",
                order_key="1",
                title="A1",
                depends_on=["item-a2", "item-b"],
            ),
            "item-a2": _item(
                "item-a2",
                parent_id="item-a",
                order_key="2",
                title="A2",
            ),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
            ),
        },
    )
    units = derive_sub_tdp_units(plan)
    unit_a = next(u for u in units if u.plan_item_id == "item-a")
    classified = classify_item_dependencies(plan, unit_a, units)
    assert classified["item-a1"]["internal"] == ["item-a2"]
    assert classified["item-a1"]["external"] == [
        {
            "dependency_item_id": "item-b",
            "owning_unit_id": "item-b",
        }
    ]


def test_self_dependency_rejected_after_normalization() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="A.",
            directory="01-a",
            ordinal=1,
        )
    ]
    plan = Plan(
        id="plan-self",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _root(),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="A",
                depends_on=["item-a"],
            ),
        },
    )
    deps = derive_unit_dependencies(plan, units)
    assert deps["item-a"] == []
