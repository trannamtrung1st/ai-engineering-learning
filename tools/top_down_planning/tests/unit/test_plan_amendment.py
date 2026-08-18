"""Tests for controlled plan amendment orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import ProductionAgentService, RequestError
from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import PlanAmendmentOrchestrator, ProductionPhaseOrchestrator, ProviderRunError
from top_down_planning.orchestrator.phases import PLAN_AMENDMENT, PRODUCTION, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import (
    capability_token_file_path,
    read_capability_token_file,
)
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    create_run_kwargs,
    done_events,
    ensure_plan_work_scope_contracts,
    grant_capability,
    plan_root_item,
    respond_review,
    script_mandatory_clear_approval,
    sessions_with_primary_session,
    whole_plan_approval_record,
    mandatory_scope_review_respond_request,
    mandatory_initial_respond_request,
)


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


def _review_respond_request(
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    target_revision: int,
) -> dict:
    return mandatory_initial_respond_request(
        store,
        run_id,
        loop_id="review-whole-plan-02",
        target_revision=target_revision,
        review_type="whole_plan",
        decision=decision,
    )


def _create_run_in_production_with_sessions(
    store: FileRunStore,
    provider: StubProvider,
    run_id: str = "run-20260101T001901-001901",
    *,
    amendment_limits: dict | None = None,
) -> tuple[str, str]:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
        kind="work",
    )
    plan = ensure_plan_work_scope_contracts(
        Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
        )
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
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    store.save_review(run_id, whole_plan_approval_record(
        store,
        run_id,
        id="review-whole-plan-01",
        reviewer_session_id="stub-session-reviewer-initial",
    ))

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
    config = store.load_resolved_config(run_id)
    run["sessions"] = sessions_with_primary_session(
        planner=planner_session_id,
        producer=producer_session_id,
        config=config,
        workspace=store.root,
    )
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
    service = ProductionAgentService(store, "run-20260101T001901-001901")

    service.apply(
        _batch_apply_request(
            plan_items=["item-first"],
            dispositions={"item-first": {"disposition": "completed"}},
        ),
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )
    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "Missing API branch in approved plan.",
            "affected_refs": ["item-root"],
            "summary": "Need API subtree.",
        },
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )

    run_id = "run-20260101T001901-001901"
    provider.script_turn(
        done_events(signal="amendment_revision_ready", text="amendment turn"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "add_item",
                    "temp_id": "item-third",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "Third",
                        "outcome": "Third outcome.",
                        "scope": {"includes": ["Third capability"]},
                    },
                }
            ],
            phase=PLAN_AMENDMENT,
        ),
    )
    provider.script_turn(
        done_events(text="review turn"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-02",
                target_revision=1,
                review_type="whole_plan",
            ),
            phase="whole_plan_review",
            loop_id="review-whole-plan-02",
        )(),
    )
    provider.script_turn(
        done_events(text="blocker review turn"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-02",
                target_revision=1,
                review_type="whole_plan",
            ),
            phase="whole_plan_review",
            loop_id="review-whole-plan-02",
        )(),
    )

    amendment_result = PlanAmendmentOrchestrator(store, run_id, provider).run()

    assert amendment_result.ok is True
    run_after = store.load_run(run_id)
    from top_down_planning.orchestrator.planner_session import primary_planner_provider_session_id

    assert amendment_result.planner_session_id == primary_planner_provider_session_id(run_after)
    assert amendment_result.producer_session_id == producer_session_id

    token_path = capability_token_file_path(store, run_id)
    assert token_path.is_file()
    producer_capability = read_capability_token_file(token_path)
    assert producer_capability
    assert (
        authorize_mutation(
            store,
            run_id,
            operation="production_apply",
            capability_token=producer_capability,
        ).role
        == "producer"
    )

    plan = store.load_plan_model("run-20260101T001901-001901")
    new_item_ids = sorted(
        item_id
        for item_id in plan.items
        if item_id not in {"item-root", "item-first", "item-second"}
    )
    assert len(new_item_ids) == 1
    new_item_id = new_item_ids[0]

    production = store.load_production("run-20260101T001901-001901")
    service.apply(
        _batch_apply_request(
            plan_items=["item-second", new_item_id],
            dispositions={
                "item-second": {"disposition": "completed"},
                new_item_id: {"disposition": "completed"},
            },
            production_revision=int(production["revision"]),
        ),
        capability_token=producer_capability,
    )
    service.submit_completion(
        {"goal_assessment": "Output goal is fully met.", "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"])},
        capability_token=producer_capability,
    )

    production = store.load_production("run-20260101T001901-001901")
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
    service = ProductionAgentService(store, "run-20260101T001901-001901")

    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )

    with pytest.raises(RequestError, match="paused while a plan amendment is pending"):
        service.apply(
            _batch_apply_request(
                plan_items=["item-first"],
                dispositions={"item-first": {"disposition": "completed"}},
                production_revision=1,
            ),
            capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
        )


def test_amendment_max_requests_is_enforced(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(
        store,
        provider,
        amendment_limits={"max_requests": 1},
    )
    service = ProductionAgentService(store, "run-20260101T001901-001901")

    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "First defect.",
            "affected_refs": ["item-root"],
            "summary": "First amendment.",
        },
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )

    production = store.load_production("run-20260101T001901-001901")
    production = dict(production)
    production["pending_amendment_id"] = None
    production["amendment_requests"][0]["status"] = "completed"
    production["revision"] = int(production["revision"]) + 1
    store.save_production("run-20260101T001901-001901", production, int(production["revision"]) - 1)

    with pytest.raises(RequestError, match="amendment limit exceeded"):
        service.request_amendment(
            {
                "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
                "evidence": "Second defect.",
                "affected_refs": ["item-root"],
                "summary": "Second amendment.",
            },
            capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
        )


def test_plan_apply_during_production_still_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    run_id = "run-20260101T001901-001901"
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[],
            role="producer",
            phase=PRODUCTION,
        ),
    )

    with pytest.raises(CapabilityDeniedError, match="plan_apply"):
        ProductionPhaseOrchestrator(store, run_id, provider).run()


def test_submit_completion_rejected_while_amendment_pending(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-20260101T001901-001901")

    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )

    with pytest.raises(RequestError, match="paused while a plan amendment is pending"):
        service.submit_completion(
            {"goal_assessment": "Output goal is fully met.", "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"])},
            capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
        )


def test_resume_routes_pending_amendment_in_whole_plan_review(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-20260101T001901-001901")
    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )

    run = store.load_run("run-20260101T001901-001901")
    production = store.load_production("run-20260101T001901-001901")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    run["status"] = "paused"
    run["stop"] = {
        "code": "amendment_pending",
        "category": "operational",
        "phase": WHOLE_PLAN_REVIEW,
        "message": "test fixture pause",
        "details": {"pending_amendment_id": production.get("pending_amendment_id")},
    }
    store.save_run("run-20260101T001901-001901", run, expected_revision)

    production = store.load_production("run-20260101T001901-001901")
    requests = list(production["amendment_requests"])
    requests[0]["prior_plan_snapshot"] = store.load_plan_model("run-20260101T001901-001901").to_dict()
    production = dict(production)
    production["amendment_requests"] = requests
    production["revision"] = int(production["revision"]) + 1
    store.save_production("run-20260101T001901-001901", production, int(production["revision"]) - 1)

    run_id = "run-20260101T001901-001901"
    provider.script_turn(
        done_events(text="review turn"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            _review_respond_request(
                store,
                run_id,
                decision="approved",
                target_revision=0,
            ),
            phase="whole_plan_review",
            loop_id="review-whole-plan-02",
        )(),
    )
    provider.script_turn(
        done_events(text="blocker review turn"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-02",
                target_revision=0,
                review_type="whole_plan",
            ),
            phase="whole_plan_review",
            loop_id="review-whole-plan-02",
        )(),
    )

    result = PlanAmendmentOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PRODUCTION
    production = store.load_production("run-20260101T001901-001901")
    assert production["pending_amendment_id"] is None
    assert production["reconciliation_reports"]


def test_resume_amendment_requires_prior_plan_snapshot(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    service = ProductionAgentService(store, "run-20260101T001901-001901")
    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=grant_capability(store, "run-20260101T001901-001901", role="producer", phase=PRODUCTION),
    )

    run = store.load_run("run-20260101T001901-001901")
    production = store.load_production("run-20260101T001901-001901")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = "plan_amendment"
    run["status"] = "paused"
    run["stop"] = {
        "code": "amendment_pending",
        "category": "operational",
        "phase": "plan_amendment",
        "message": "test fixture pause",
        "details": {"pending_amendment_id": production.get("pending_amendment_id")},
    }
    store.save_run("run-20260101T001901-001901", run, expected_revision)

    with pytest.raises(ProviderRunError, match="prior_plan_snapshot"):
        PlanAmendmentOrchestrator(store, "run-20260101T001901-001901", provider).run()


def test_amendment_activation_persists_revoke_all_when_cleanup_fails(tmp_path: Path) -> None:
    from unittest.mock import patch

    from top_down_planning.orchestrator.run_transitions import (
        pending_capability_revoke_all,
        reconcile_pending_capability_revocation,
    )

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_in_production_with_sessions(store, provider)
    run_id = "run-20260101T001901-001901"
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    token_id = token.split(".", 1)[0]

    service = ProductionAgentService(store, run_id)
    service.request_amendment(
        {
            "production_revision": int(store.load_production("run-20260101T001901-001901")["revision"]),
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=token,
    )

    run = store.load_run(run_id)
    production = store.load_production(run_id)
    expected_revision = int(run["revision"])
    paused = dict(run)
    paused["revision"] = expected_revision + 1
    paused["phase"] = PLAN_AMENDMENT
    paused["status"] = "paused"
    paused["stop"] = {
        "code": "amendment_pending",
        "category": "operational",
        "phase": PLAN_AMENDMENT,
        "message": "test fixture pause",
        "details": {"pending_amendment_id": production.get("pending_amendment_id")},
    }
    store.save_run(run_id, paused, expected_revision)

    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    with patch.object(store, "revoke_capability", side_effect=OSError("revoke failed")):
        activated = orch._activate_amendment_execution()

    assert activated["status"] == "running"
    assert activated["phase"] == PLAN_AMENDMENT
    assert pending_capability_revoke_all(activated) is True
    assert store.load_capability(run_id, token_id)["revoked"] is False

    reconcile_pending_capability_revocation(store, run_id)
    reconciled = store.load_run(run_id)
    assert pending_capability_revoke_all(reconciled) is False
    assert store.load_capability(run_id, token_id)["revoked"] is True
