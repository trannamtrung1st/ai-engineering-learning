"""Tests for Sub-TDP unit decomposition from approved plan."""

from __future__ import annotations

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_units import (
    derive_sub_tdp_units,
    slug_from_title,
)


def _plan_with_root_children() -> Plan:
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-a",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Persistence foundation",
        outcome="Persist state reliably.",
        kind="work",
        scope=Scope(includes=["storage"]),
    )
    second = PlanItem(
        id="item-b",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000001",
        title="Board structure",
        outcome="Board lifecycle works.",
        kind="work",
        scope=Scope(includes=["board"]),
    )
    return Plan(
        id="plan-test",
        revision=1,
        output_goal="Ship the product.",
        items={
            PLAN_ROOT_ITEM_ID: root,
            "item-a": first,
            "item-b": second,
        },
    )


def test_derive_sub_tdp_units_from_root_children_ordered() -> None:
    units = derive_sub_tdp_units(_plan_with_root_children())
    assert len(units) == 2
    assert units[0].plan_item_id == "item-a"
    assert units[1].plan_item_id == "item-b"
    assert units[0].directory == "01-persistence-foundation"
    assert units[1].directory == "02-board-structure"


def test_derive_sub_tdp_units_rejects_empty_root_children() -> None:
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver.",
        kind="aggregate",
    )
    plan = Plan(
        id="plan-empty",
        revision=0,
        output_goal="Goal.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    with pytest.raises(ValueError, match="no active root children"):
        derive_sub_tdp_units(plan)


def test_slug_from_title_sanitizes() -> None:
    assert slug_from_title("Board structure & lifecycle") == "board-structure-lifecycle"
