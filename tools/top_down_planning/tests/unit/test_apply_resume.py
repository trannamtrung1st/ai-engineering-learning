"""apply_resume_plan_atomically() tests (proposal §9.3, §17, §21)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.apply_resume import (
    ApplyResumeError,
    apply_resume_plan_atomically,
)
from top_down_planning.orchestrator.failure import apply_review_incomplete_run_transition
from top_down_planning.orchestrator.phases import PLANNING, PLAN_AMENDMENT, PRODUCTION, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.prepare_resume import PrepareResumeBlockedError, prepare_resume
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    create_run_kwargs,
    minimal_resolved_config,
    whole_plan_approval_record,
)


def _sample_plan() -> Plan:
    return Plan(
        id="plan-run-test",
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


def _create_production_run(
    store: FileRunStore,
    *,
    run_id: str = "run-20260101T001201-001201",
    status: str = "running",
    phase: str = PRODUCTION,
) -> str:
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=phase,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = status
    run["revision"] = expected_revision + 1
    if status == "paused":
        run["stop"] = {
            "code": "limit_exhausted",
            "category": "operational",
            "phase": phase,
            "message": "limit reached",
            "details": {
                "limit": "limits.production.max_batches",
                "consumed": 1,
                "configured": 1,
            },
        }
    store.save_run(run_id, run, expected_revision)
    return run_id


def _paused_planning_run(store: FileRunStore, run_id: str = "run-20260101T001301-001301") -> str:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["planning"] = {"agent_turns": 5, "items_added": 2}
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PLANNING,
        "message": "limit reached",
        "details": {
            "limit": "limits.planning.max_agent_turns",
            "consumed": 5,
            "configured": 5,
        },
    }
    store.save_run(run_id, run, expected_revision)
    return run_id


def test_resume_applied_event_shape(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"] = copy.deepcopy(stored["limits"])
    candidate["limits"]["production"] = copy.deepcopy(stored["limits"]["production"])
    candidate["limits"]["production"]["max_batches"] = 99
    invocation = store.load_invocation(run_id)

    plan = prepare_resume(store, run_id, candidate)
    result = apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=candidate,
        invocation=invocation,
    )

    run = store.load_run(run_id)
    assert result["ok"] is True
    assert run["status"] == "running"
    assert run["stop"] is None
    events = store.load_events(run_id)
    applied = [event for event in events if event.get("type") == "resume_applied"]
    assert len(applied) == 1
    event = applied[0]
    assert event["run_id"] == run_id
    assert event["expected_revision"] == plan.expected_run_revision
    assert event["resulting_revision"] == run["revision"]
    assert event["phase"] == PRODUCTION
    assert event["prior_status"] == "paused"
    assert event["prior_stop"]["code"] == "limit_exhausted"
    assert "limits.production.max_batches" in event["config_changes"]
    assert event["old_config_execution_digest"]
    assert event["new_config_execution_digest"] == run["digests"]["config_execution"]
    assert event["session_policy"]
    assert event["invocation"]


def test_resume_limit_extended_event(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"]["production"]["max_batches"] = 99
    plan = prepare_resume(store, run_id, candidate)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=candidate,
        invocation=store.load_invocation(run_id),
    )
    events = store.load_events(run_id)
    extended = [event for event in events if event.get("type") == "resume_limit_extended"]
    assert len(extended) == 1
    assert "limits.production.max_batches" in extended[0]["paths"]


def test_resume_limit_only_counters_unchanged(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _paused_planning_run(store)
    before = dict(store.load_run(run_id).get("planning") or {})
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"]["planning"]["max_agent_turns"] = 80
    plan = prepare_resume(store, run_id, candidate)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=candidate,
        invocation=store.load_invocation(run_id),
    )
    after = dict(store.load_run(run_id).get("planning") or {})
    assert after == before


def _set_paused_stop(
    store: FileRunStore,
    run_id: str,
    stop: dict,
    *,
    extra_run_fields: dict | None = None,
) -> None:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = stop
    if extra_run_fields:
        run.update(extra_run_fields)
    store.save_run(run_id, run, expected_revision)


def test_resume_provider_unavailable(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused", phase=PRODUCTION)
    _set_paused_stop(
        store,
        run_id,
        {
            "code": "provider_unavailable",
            "category": "operational",
            "phase": PRODUCTION,
            "message": "provider unavailable",
            "details": {},
        },
    )
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    assert store.load_run(run_id)["status"] == "running"


def test_resume_provider_turn_failed_requires_phase_action_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    _set_paused_stop(
        store,
        run_id,
        {
            "code": "provider_turn_failed",
            "category": "operational",
            "phase": PRODUCTION,
            "message": "turn failed",
            "details": {},
        },
        extra_run_fields={"phase_action_id": None},
    )
    stored = store.load_resolved_config(run_id)
    with pytest.raises(PrepareResumeBlockedError, match="phase_action_id"):
        prepare_resume(store, run_id, stored)


def test_resume_provider_turn_failed_success(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    _set_paused_stop(
        store,
        run_id,
        {
            "code": "provider_turn_failed",
            "category": "operational",
            "phase": PRODUCTION,
            "message": "turn failed",
            "details": {},
        },
        extra_run_fields={"phase_action_id": "action-test-01"},
    )
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    assert store.load_run(run_id)["status"] == "running"


def test_resume_user_cancelled(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    _set_paused_stop(
        store,
        run_id,
        {
            "code": "user_cancelled",
            "category": "operational",
            "phase": PRODUCTION,
            "message": "cancelled",
            "details": {},
        },
    )
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    assert store.load_run(run_id)["status"] == "running"


def test_resume_amendment_pending(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused", phase=PLAN_AMENDMENT)
    production = store.load_production(run_id)
    pending_id = "amendment-req-01"
    production = dict(production)
    production["pending_amendment_id"] = pending_id
    production["amendment_requests"] = [
        {
            "id": pending_id,
            "status": "pending",
            "summary": "Need change",
            "evidence": "x",
            "affected_refs": ["item-root"],
        }
    ]
    expected_production_revision = int(production["revision"])
    production["revision"] = expected_production_revision + 1
    store.save_production(run_id, production, expected_revision=expected_production_revision)
    _set_paused_stop(
        store,
        run_id,
        {
            "code": "amendment_pending",
            "category": "operational",
            "phase": PLAN_AMENDMENT,
            "message": "amendment pending",
            "details": {"pending_amendment_id": pending_id},
        },
    )
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    assert store.load_run(run_id)["status"] == "running"


def test_resume_mandatory_review_incomplete_continue(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001401-001401"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=WHOLE_PLAN_REVIEW,
        **create_run_kwargs(store.root),
    )
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="review_incomplete",
        lifecycle_status="review_incomplete",
        revise_at="blocker",
        finding_set_id="fs-01",
        review_incomplete={
            "stage": "discovery",
            "finding_set_id": "fs-01",
            "reason": "missing inputs",
        },
    )
    store.save_review(run_id, loop.to_dict())
    apply_review_incomplete_run_transition(
        store,
        run_id,
        loop_id=loop.id,
        reason="missing inputs",
        finding_set_id="fs-01",
        stage="discovery",
    )
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    persisted = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert persisted.status == "pending"
    assert persisted.lifecycle_status == "review_pending"
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run["stop"] is None
    events = store.load_events(run_id)
    assert any(event.get("type") == "resume_applied" for event in events)


def test_stale_resume_plan_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="paused")
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"]["production"]["max_batches"] = 99
    plan = prepare_resume(store, run_id, candidate)
    run = store.load_run(run_id)
    run["revision"] = int(run["revision"]) + 1
    store.save_run(run_id, run, expected_revision=int(run["revision"]) - 1)
    with pytest.raises(ApplyResumeError, match="revision"):
        apply_resume_plan_atomically(
            store,
            plan,
            resolved_config=candidate,
            invocation=store.load_invocation(run_id),
        )


def test_running_continuation_apply_emits_resume_applied(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run(store, status="running")
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )
    events = store.load_events(run_id)
    assert any(event.get("type") == "resume_applied" for event in events)
    assert store.load_run(run_id)["status"] == "running"
