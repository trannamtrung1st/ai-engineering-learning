"""Tests for controlled plan amendment orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import ProductionAgentService, RequestError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import PlanAmendmentOrchestrator, ProductionPhaseOrchestrator, ProviderRunError
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import done_events


def _batch_apply_request(
    *,
    plan_items: list[str],
    dispositions: dict,
    production_revision: int = 0,
) -> dict:
    return {
        "production_revision": production_revision,
        "plan_items": plan_items,
        "dispositions": dispositions,
        "outputs": [],
        "contributions": [],
        "summary": "batch complete",
    }


def _review_respond_request(*, decision: str, target_revision: int) -> dict:
    return {
        "loop_id": "review-whole-plan-02",
        "target_revision": target_revision,
        "decision": decision,
        "findings": [],
    }


def _create_run_in_production_with_sessions(
    store: FileRunStore,
    provider: StubProvider,
    run_id: str = "run-amendment",
    *,
    amendment_limits: dict | None = None,
) -> tuple[str, str]:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )
    limits: dict = {
        "production": {"max_batches": 50, "max_agent_turns_per_batch": 10},
        "whole_plan_review": {"max_revision_cycles": 5},
        "amendment": {"max_requests": 3, "max_revision_cycles_per_request": 3},
    }
    if amendment_limits:
        limits["amendment"].update(amendment_limits)

    config = {
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": limits,
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest="input-a",
        output_goal_digest="goal-b",
        phase=PRODUCTION,
    )
    store.save_review(
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "stub-session-reviewer-initial",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "approved",
            "findings": [],
            "revision_cycles": 0,
        },
    )

    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(text="producer session start"))

    planner_session_id = provider.start_primary_session(
        "planner",
        {"run_id": run_id, "phase": "planning"},
    )
    list(provider.stream_events(planner_session_id))
    producer_session_id = provider.start_primary_session(
        "producer",
        {"run_id": run_id, "phase": PRODUCTION},
    )
    list(provider.stream_events(producer_session_id))

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {
        "primary_planner_session_id": planner_session_id,
        "primary_producer_session_id": producer_session_id,
    }
    store.save_run(run_id, run, expected_revision)
    return planner_session_id, producer_session_id


def test_mid_production_amendment_adds_item_and_preserves_evidence(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    planner_session_id, producer_session_id = _create_run_in_production_with_sessions(
        store,
        provider,
    )
    service = ProductionAgentService(store, "run-amendment")

    service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        role="producer",
    )
    service.request_amendment(
        {
            "evidence": "Missing API branch in approved plan.",
            "affected_refs": ["item-root"],
            "summary": "Need API subtree.",
        },
        role="producer",
    )

    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "plan_apply",
                "role": "planner",
                "request": {
                    "base_revision": 0,
                    "operations": [
                        {
                            "op": "add_item",
                            "temp_id": "item-third",
                            "parent_id": "item-root",
                            "placement": {"last_child": True},
                            "item": {
                                "title": "Third",
                                "outcome": "Third outcome.",
                            },
                        }
                    ],
                },
            },
            *done_events(signal="amendment_revision_ready", text="amendment turn"),
        ]
    )
    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "review_respond",
                "role": "reviewer",
                "request": _review_respond_request(
                    decision="approved",
                    target_revision=1,
                ),
            },
            *done_events(text="review turn"),
        ]
    )

    amendment_result = PlanAmendmentOrchestrator(store, "run-amendment", provider).run()

    assert amendment_result.ok is True
    assert amendment_result.planner_session_id == planner_session_id
    assert amendment_result.producer_session_id == producer_session_id

    plan = store.load_plan_model("run-amendment")
    new_item_ids = sorted(
        item_id
        for item_id in plan.items
        if item_id not in {"item-root", "item-first", "item-second"}
    )
    assert len(new_item_ids) == 1
    new_item_id = new_item_ids[0]

    production = store.load_production("run-amendment")
    service.apply(
        _batch_apply_request(
            plan_items=["item-second", new_item_id],
            dispositions={
                "item-second": {"disposition": "completed"},
                new_item_id: {"disposition": "completed"},
            },
            production_revision=int(production["revision"]),
        ),
        role="producer",
    )
    service.submit_completion(
        {"goal_assessment": "Output goal is fully met."},
        role="producer",
    )

    production = store.load_production("run-amendment")
    assert production["pending_amendment_id"] is None
    assert production["dispositions"]["item-first"] == "completed"
    assert production["dispositions"]["item-second"] == "completed"
    assert production["dispositions"][new_item_id] == "completed"
    assert production["amendment_requests"][0]["status"] == "completed"
    reconciliation = production["reconciliation_reports"][0]
    assert new_item_id in reconciliation["newly_added"]
    assert "item-first" in reconciliation["evidence_preserved"]
    assert len(production["batches"]) == 2


def test_apply_rejected_while_amendment_pending(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-amendment")

    service.request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        role="producer",
    )

    with pytest.raises(RequestError, match="paused while a plan amendment is pending"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
                production_revision=1,
            ),
            role="producer",
        )


def test_amendment_max_requests_is_enforced(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(
        store,
        provider,
        amendment_limits={"max_requests": 1},
    )
    service = ProductionAgentService(store, "run-amendment")

    service.request_amendment(
        {
            "evidence": "First defect.",
            "affected_refs": ["item-root"],
            "summary": "First amendment.",
        },
        role="producer",
    )

    production = store.load_production("run-amendment")
    production = dict(production)
    production["pending_amendment_id"] = None
    production["amendment_requests"][0]["status"] = "completed"
    production["revision"] = int(production["revision"]) + 1
    store.save_production("run-amendment", production, int(production["revision"]) - 1)

    with pytest.raises(RequestError, match="amendment limit exceeded"):
        service.request_amendment(
            {
                "evidence": "Second defect.",
                "affected_refs": ["item-root"],
                "summary": "Second amendment.",
            },
            role="producer",
        )


def test_plan_apply_during_production_still_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "plan_apply",
                "role": "producer",
                "request": {
                    "base_revision": 0,
                    "operations": [],
                },
            },
            *done_events(signal="batch_complete", text="production turn"),
        ]
    )

    with pytest.raises(ProviderRunError, match="plan mutations are not allowed"):
        ProductionPhaseOrchestrator(store, "run-amendment", provider).run()


def test_submit_completion_rejected_while_amendment_pending(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-amendment")

    service.request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        role="producer",
    )

    with pytest.raises(RequestError, match="paused while a plan amendment is pending"):
        service.submit_completion(
            {"goal_assessment": "Output goal is fully met."},
            role="producer",
        )


def test_resume_routes_pending_amendment_in_whole_plan_review(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-amendment")
    service.request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        role="producer",
    )

    run = store.load_run("run-amendment")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = "whole_plan_review"
    run["status"] = "paused"
    store.save_run("run-amendment", run, expected_revision)

    production = store.load_production("run-amendment")
    requests = list(production["amendment_requests"])
    requests[0]["prior_plan_snapshot"] = store.load_plan_model("run-amendment").to_dict()
    production = dict(production)
    production["amendment_requests"] = requests
    production["revision"] = int(production["revision"]) + 1
    store.save_production("run-amendment", production, int(production["revision"]) - 1)

    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "review_respond",
                "role": "reviewer",
                "request": _review_respond_request(
                    decision="approved",
                    target_revision=0,
                ),
            },
            *done_events(text="review turn"),
        ]
    )

    result = PlanAmendmentOrchestrator(store, "run-amendment", provider).run()

    assert result.ok is True
    assert result.phase == PRODUCTION
    production = store.load_production("run-amendment")
    assert production["pending_amendment_id"] is None
    assert production["reconciliation_reports"]


def test_resume_amendment_requires_prior_plan_snapshot(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-amendment")
    service.request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        role="producer",
    )

    run = store.load_run("run-amendment")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = "plan_amendment"
    run["status"] = "paused"
    store.save_run("run-amendment", run, expected_revision)

    with pytest.raises(ProviderRunError, match="prior_plan_snapshot"):
        PlanAmendmentOrchestrator(store, "run-amendment", provider).run()
