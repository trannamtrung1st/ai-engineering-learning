"""Security tests for hashed, session-bound, revocable capabilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, grant_capability, mandatory_initial_respond_request, mandatory_plan_digest, minimal_resolved_config, save_review_payload


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T000901-000901") -> None:
    workspace = store.root
    config = minimal_resolved_config()
    plan = Plan(
        id="plan-run-20260101T000901-000901",
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
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=config),
    )


def test_capability_record_stores_hash_not_secret(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    token = grant_capability(store, "run-20260101T000901-000901", role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    record = store.load_capability("run-20260101T000901-000901", token_id)
    assert "secret_hash" in record
    assert "secret" not in record
    path = store.capabilities_dir("run-20260101T000901-000901") / f"{token_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "secret_hash" in payload
    assert "secret" not in payload


def test_wrong_session_is_denied(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    token = grant_capability(
        store,
        "run-20260101T000901-000901",
        role="planner",
        phase=PLANNING,
        session_id="other-planner",
    )
    run = store.load_run("run-20260101T000901-000901")
    from top_down_planning.persistence.session_bindings import update_primary_binding

    sessions = update_primary_binding(
        dict(run.get("sessions") or {}),
        role="planner",
        provider_session_id="active-planner",
    )
    run = dict(run)
    run["sessions"] = sessions
    expected = int(run["revision"])
    run["revision"] = expected + 1
    store.save_run("run-20260101T000901-000901", run, expected)

    with pytest.raises(CapabilityDeniedError, match="session"):
        authorize_mutation(store, "run-20260101T000901-000901", operation="plan_apply", capability_token=token)


def test_revoked_token_is_denied(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    token = grant_capability(store, "run-20260101T000901-000901", role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    store.revoke_capability("run-20260101T000901-000901", token_id)
    with pytest.raises(CapabilityDeniedError, match="revoked"):
        authorize_mutation(store, "run-20260101T000901-000901", operation="plan_apply", capability_token=token)


def test_phase_leave_revokes_capabilities(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    token = grant_capability(store, "run-20260101T000901-000901", role="planner", phase=PLANNING)
    revoke_capabilities_for_phase(store, "run-20260101T000901-000901", PLANNING)
    with pytest.raises(CapabilityDeniedError, match="revoked"):
        authorize_mutation(store, "run-20260101T000901-000901", operation="plan_apply", capability_token=token)


def test_planner_cannot_use_reviewer_authority_from_disk(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run = store.load_run("run-20260101T000901-000901")
    run = dict(run)
    run["phase"] = WHOLE_PLAN_REVIEW
    expected = int(run["revision"])
    run["revision"] = expected + 1
    store.save_run("run-20260101T000901-000901", run, expected)

    save_review_payload(store, "run-20260101T000901-000901", {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "reviewer-session-01",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "finding_set_id": "review-whole-plan-01-fs-01",
        },
    )
    reviewer_token = grant_capability(
        store,
        "run-20260101T000901-000901",
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="reviewer-session-01",
        loop_id="review-whole-plan-01",
    )
    planner_token = grant_capability(
        store,
        "run-20260101T000901-000901",
        role="planner",
        phase=WHOLE_PLAN_REVIEW,
        session_id="planner-session-01",
    )

    # Planner reading capability files cannot reconstruct reviewer secret.
    for path in store.capabilities_dir("run-20260101T000901-000901").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("role") != "reviewer" or "secret" not in payload

    run_id = "run-20260101T000901-000901"
    plan_digest = mandatory_plan_digest(store, run_id)
    service = ReviewAgentService(store, run_id)
    with pytest.raises(CapabilityDeniedError):
        service.respond(
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                decision="approved",
            ),
            capability_token=planner_token,
        )

    wrong_loop_token = grant_capability(
        store,
        "run-20260101T000901-000901",
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="reviewer-session-02",
        loop_id="review-whole-plan-01",
    )
    save_review_payload(store, "run-20260101T000901-000901",
        ReviewLoop.from_dict(
            store.load_review("run-20260101T000901-000901", "review-whole-plan-01")
        )
        .with_reviewer_provider_session_id("reviewer-session-01")
        .to_dict(),
    )
    with pytest.raises(CapabilityDeniedError, match="session"):
        service.respond(
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                decision="approved",
            ),
            capability_token=wrong_loop_token,
        )

    # Leaked reviewer token from the correct session still works.
    service.respond(
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
            decision="approved",
        ),
        capability_token=reviewer_token,
    )
