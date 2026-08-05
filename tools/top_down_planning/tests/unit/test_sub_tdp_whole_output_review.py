"""Tests for Sub-TDP whole-output review adapter."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_synthesis import synthesize_parent_production
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_OUTPUT_REVIEW
from core_tools.provider import StubProvider
from top_down_planning.orchestrator.whole_output_review import (
    SubTdpWholeOutputReviewAdapter,
    WholeOutputReviewOrchestrator,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state
from tests.helpers import create_run_kwargs, whole_plan_approval_record


def _parent_plan(run_id: str) -> Plan:
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
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship the product.",
        items={PLAN_ROOT_ITEM_ID: root, "item-a": first},
    )


def test_sub_tdp_whole_output_review_package_includes_child_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    workspace = tmp_path
    config = create_run_kwargs(workspace)["resolved_config"]
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_parent_plan(run_id),
        phase=PLAN_VALIDATED,
        workspace=str(workspace),
        invocation={"command": "execute", "observability": {}},
        run_extras={"run_kind": "parent_execution"},
        **{k: v for k, v in kwargs.items() if k not in {"workspace", "invocation"}},
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="Persistence foundation",
            outcome="Persist state reliably.",
            directory="01-persistence-foundation",
            ordinal=1,
        ),
    ]
    production = store.load_production(run_id)
    production["sub_tdps"] = initial_sub_tdp_state(units)
    unit_record = production["sub_tdps"]["units"][0]
    unit_record["child_run_id"] = "run-child-01"
    unit_record["status"] = "completed"
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
    }
    synthesized = synthesize_parent_production(
        _parent_plan(run_id),
        production,
        child_runs=[(unit_record, child_run, child_production)],
        parent_output_goal="Ship the product.",
    )
    store.save_production(run_id, synthesized, int(production["revision"]))

    run = store.load_run(run_id)
    expected_run_revision = int(run["revision"])
    run = dict(run)
    run["phase"] = WHOLE_OUTPUT_REVIEW
    run["revision"] = expected_run_revision + 1
    store.save_run(run_id, run, expected_run_revision)

    adapter = SubTdpWholeOutputReviewAdapter(store, run_id)
    adapter.preflight(None)
    loop = adapter.new_loop("review-whole-output-01")
    package = adapter.build_review_package(
        store.load_run(run_id),
        store.load_resolved_config(run_id),
        loop,
    )
    assert package["sub_tdp_evidence"]
    assert package["integrated_deliverables"]
    assert package["sub_tdp_evidence"][0]["child_run_id"] == "run-child-01"


def test_whole_output_review_orchestrator_uses_sub_tdp_adapter(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    workspace = tmp_path
    config = create_run_kwargs(workspace)["resolved_config"]
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_parent_plan(run_id),
        phase=WHOLE_OUTPUT_REVIEW,
        workspace=str(workspace),
        invocation={"command": "execute", "observability": {}},
        run_extras={"run_kind": "parent_execution"},
        **{k: v for k, v in kwargs.items() if k not in {"workspace", "invocation"}},
    )
    production = store.load_production(run_id)
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="Persistence foundation",
            outcome="Persist state reliably.",
            directory="01-persistence-foundation",
            ordinal=1,
        ),
    ]
    production["sub_tdps"] = initial_sub_tdp_state(units)
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "Integrated delivery meets parent goal.",
    }
    production["batches"] = [
        {
            "id": "batch-integration-01",
            "plan_items": ["item-a"],
            "status": "completed",
            "agent_turns": 0,
            "intent": "sub_tdp_integration",
            "result": {
                "outputs": [],
                "contributions": [],
                "dispositions": {"item-a": {"disposition": "completed"}},
                "summary": "integration",
                "empty_output": False,
                "goal_assessment": "Integrated delivery meets parent goal.",
            },
        }
    ]
    production["dispositions"] = {"item-a": {"disposition": "completed"}}
    expected_production_revision = int(production["revision"])
    production["revision"] = expected_production_revision + 1
    store.save_production(run_id, production, expected_production_revision)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    orchestrator = WholeOutputReviewOrchestrator(store, run_id, StubProvider())
    assert isinstance(orchestrator._driver._adapter, SubTdpWholeOutputReviewAdapter)
