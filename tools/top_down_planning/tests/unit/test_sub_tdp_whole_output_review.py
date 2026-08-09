"""Tests for Sub-TDP whole-output review adapter."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_synthesis import synthesize_parent_production
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_OUTPUT_REVIEW
from core_tools.provider import StubProvider
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.whole_output_review import (
    SubTdpWholeOutputReviewAdapter,
    WholeOutputReviewOrchestrator,
)
from top_down_planning.package.lineage import (
    accepted_result_digest,
    accepted_result_record,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state
from tests.helpers import (
    accept_child_run,
    create_run_kwargs,
    decorate_sub_tdp_v2_package,
    goal_met_completion_claim,
    whole_plan_approval_record,
)
from tests.unit.test_prepared_runs import _built_package
import pytest


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
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute"},
    )
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)

    units = [
        SubTdpUnit(
            plan_item_id=u.unit_id,
            title=u.title,
            outcome="",
            directory=u.plan_file.parent.name,
            ordinal=u.ordinal,
        )
        for u in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    production = store.load_production(parent_id)
    foundation = package.units["item-foundation"]
    production["sub_tdps"] = decorate_sub_tdp_v2_package(
        initial_sub_tdp_state(units),
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        unit_plan_digest=foundation.plan_digest,
        assigned_subtree_digest=foundation.assigned_subtree_digest,
    )
    unit_record = production["sub_tdps"]["units"][0]
    accepted = accepted_result_record(
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        unit_id="item-foundation",
        unit_plan_digest=package.units["item-foundation"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-foundation"].assigned_subtree_digest,
    )
    unit_record["child_run_id"] = child_id
    unit_record["status"] = "completed"
    unit_record["accepted_result"] = accepted
    unit_record["accepted_result_digest"] = accepted_result_digest(accepted)

    child_run = store.load_run(child_id)
    child_production = store.load_production(child_id)
    synthesized = synthesize_parent_production(
        store.load_plan_model(parent_id),
        production,
        child_runs=[(unit_record, child_run, child_production)],
        parent_output_goal="Ship the product.",
    )
    synthesized["completion_claim"] = goal_met_completion_claim(
        synthesized,
        goal_assessment="Parent integration validated; goal met.",
    )
    store.save_production(parent_id, synthesized, int(production["revision"]))

    run = store.load_run(parent_id)
    expected_run_revision = int(run["revision"])
    run = dict(run)
    run["phase"] = WHOLE_OUTPUT_REVIEW
    run["revision"] = expected_run_revision + 1
    store.save_run(parent_id, run, expected_run_revision)

    adapter = SubTdpWholeOutputReviewAdapter(store, parent_id)
    adapter.preflight(None)
    loop = adapter.new_loop("review-whole-output-01")
    package_payload = adapter.build_review_package(
        store.load_run(parent_id),
        store.load_resolved_config(parent_id),
        loop,
    )
    assert package_payload["sub_tdp_evidence"]
    assert package_payload["integrated_deliverables"]
    assert package_payload["sub_tdp_evidence"][0]["child_run_id"] == child_id
    assert package_payload["sub_tdp_evidence"][0]["output_digest"] == accepted[
        "output_digest"
    ]


def test_sub_tdp_whole_output_review_fails_when_child_run_missing(
    tmp_path: Path,
) -> None:
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
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["sub_tdps"] = decorate_sub_tdp_v2_package(initial_sub_tdp_state(units))
    unit_record = production["sub_tdps"]["units"][0]
    unit_record["child_run_id"] = "run-20260101T000911-000911"
    unit_record["status"] = "completed"
    unit_record["accepted_result"] = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "a" * 64,
        "unit_id": "item-a",
        "unit_plan_digest": "b" * 64,
        "assigned_subtree_digest": "c" * 64,
        "child_run_id": "run-20260101T000911-000911",
        "output_revision": 1,
        "output_digest": "a" * 64,
        "whole_output_review_id": "review-whole-output-1",
        "whole_output_review_digest": "d" * 64,
        "outcome": "accepted",
        "evidence_digest": "e" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "baseline_accepted_result_digests": [],
        "final_context_snapshot_digest": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "completion_assessment": "Child goal met.",
    }
    unit_record["accepted_result_digest"] = accepted_result_digest(
        unit_record["accepted_result"]
    )
    production["completion_claim"] = goal_met_completion_claim(production)
    store.save_production(run_id, production, expected_prod)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["phase"] = WHOLE_OUTPUT_REVIEW
    run["revision"] = expected + 1
    store.save_run(run_id, run, expected)

    adapter = SubTdpWholeOutputReviewAdapter(store, run_id)
    adapter.preflight(None)
    loop = adapter.new_loop("review-whole-output-01")
    with pytest.raises(ProviderRunError, match="unable to load Sub-TDP child"):
        adapter.build_review_package(
            store.load_run(run_id),
            store.load_resolved_config(run_id),
            loop,
        )


def test_whole_output_review_orchestrator_uses_sub_tdp_adapter(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
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
    expected_prod = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_prod + 1
    production["sub_tdps"] = decorate_sub_tdp_v2_package(initial_sub_tdp_state(units))
    store.save_production(run_id, production, expected_prod)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["phase"] = WHOLE_OUTPUT_REVIEW
    run["revision"] = expected + 1
    store.save_run(run_id, run, expected)

    provider = StubProvider()
    orchestrator = WholeOutputReviewOrchestrator(store, run_id, provider)
    assert isinstance(orchestrator._driver._adapter, SubTdpWholeOutputReviewAdapter)
