"""Tests for parent production synthesis from Sub-TDP children."""

from __future__ import annotations

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_synthesis import synthesize_parent_production
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state
from top_down_planning.domain.sub_tdp_units import SubTdpUnit


def _parent_plan() -> Plan:
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
        id="plan-parent",
        revision=1,
        output_goal="Ship the product.",
        items={
            PLAN_ROOT_ITEM_ID: root,
            "item-a": first,
            "item-b": second,
        },
    )


def test_synthesize_parent_production_builds_completion_claim_and_batch() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="Persistence foundation",
            outcome="Persist state reliably.",
            directory="01-persistence-foundation",
            ordinal=1,
        ),
    ]
    production = {
        "revision": 0,
        "output_revision": 0,
        "batches": [],
        "dispositions": {},
        "output_evidence": [],
        "amendment_requests": [],
        "pending_amendment_id": None,
        "reconciliation_reports": [],
        "completion_claim": None,
        "blocker_report": None,
        "sub_tdps": initial_sub_tdp_state(units),
    }
    unit_record = production["sub_tdps"]["units"][0]
    child_run = {
        "id": "run-child-01",
        "status": "completed",
        "phase": "output_validated",
        "outcome": "accepted",
    }
    child_production = {
        "completion_claim": {
            "goal_met": True,
            "goal_assessment": "Child goal met.",
        },
        "output_evidence": [],
        "batches": [],
    }
    synthesized = synthesize_parent_production(
        _parent_plan(),
        production,
        child_runs=[(unit_record, child_run, child_production)],
        parent_output_goal="Ship the product.",
    )
    assert synthesized["completion_claim"]["goal_met"] is True
    assert synthesized["dispositions"]["item-a"] == "completed"
    assert len(synthesized["batches"]) == 1
    assert synthesized["batches"][0]["intent"] == "sub_tdp_integration"
    assert synthesized["sub_tdps"]["status"] == "completed"


def test_synthesize_rejects_non_terminal_child() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="Persistence foundation",
            outcome="Persist state reliably.",
            directory="01-persistence-foundation",
            ordinal=1,
        ),
    ]
    production = {
        "revision": 0,
        "output_revision": 0,
        "batches": [],
        "dispositions": {},
        "output_evidence": [],
        "amendment_requests": [],
        "pending_amendment_id": None,
        "reconciliation_reports": [],
        "completion_claim": None,
        "blocker_report": None,
        "sub_tdps": initial_sub_tdp_state(units),
    }
    unit_record = production["sub_tdps"]["units"][0]
    child_run = {
        "id": "run-child-01",
        "status": "running",
        "phase": "production",
        "outcome": None,
    }
    child_production = {"completion_claim": None, "output_evidence": [], "batches": []}

    with pytest.raises(ValueError, match="output_validated"):
        synthesize_parent_production(
            _parent_plan(),
            production,
            child_runs=[(unit_record, child_run, child_production)],
            parent_output_goal="Ship the product.",
        )
