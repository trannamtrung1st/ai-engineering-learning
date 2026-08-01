"""Session lineage audit event tests (§17 / item 1.4.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_lineage import (
    SESSION_PROVIDER_ID_BOUND,
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
    SESSION_RESUME_FAILED,
    session_provider_id_bound_payload,
    session_replaced_payload,
    session_replacement_failed_payload,
    session_replacement_started_payload,
    session_resume_failed_payload,
)
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.session_events import (
    commit_primary_provider_session_binding,
    commit_reviewer_loop_provider_session,
    sync_persisted_session_id,
)
from top_down_planning.orchestrator.session_lineage import (
    emit_session_replaced,
    emit_session_replacement_failed,
    emit_session_replacement_started,
    emit_session_resume_failed,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


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


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T007001-007001") -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def test_lineage_payloads_include_required_fields() -> None:
    bound = session_provider_id_bound_payload(
        run_id="run-1",
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-a1",
        generation=1,
        provider_session_id="cursor-abc",
        provider="cursor",
    )
    assert bound["type"] == SESSION_PROVIDER_ID_BOUND
    assert bound["session_instance_id"] == "tdp-session-a1"
    assert bound["generation"] == 1

    replaced = session_replaced_payload(
        run_id="run-1",
        phase=PLANNING,
        role="planner",
        old_session_instance_id="tdp-session-a1",
        new_session_instance_id="tdp-session-b2",
        generation=2,
        reason="provider_session_not_found",
        old_provider_session_id="cursor-abc",
        new_provider_session_id="cursor-xyz",
        phase_action_id="action-42",
    )
    assert replaced["type"] == SESSION_REPLACED
    assert replaced["phase_action_id"] == "action-42"

    started = session_replacement_started_payload(
        run_id="run-1",
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-b2",
        generation=2,
        reason="provider_session_not_found",
    )
    assert started["type"] == SESSION_REPLACEMENT_STARTED

    resume_failed = session_resume_failed_payload(
        run_id="run-1",
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-a1",
        generation=1,
        reason="provider_session_not_found",
        provider_session_id="cursor-abc",
    )
    assert resume_failed["type"] == SESSION_RESUME_FAILED

    replacement_failed = session_replacement_failed_payload(
        run_id="run-1",
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-b2",
        generation=2,
        reason="provider_unavailable",
    )
    assert replacement_failed["type"] == SESSION_REPLACEMENT_FAILED


def test_emit_helpers_append_lineage_events(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    _create_planning_run(store)

    emit_session_replacement_started(
        store,
        run_id,
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-b2",
        generation=2,
        reason="provider_session_not_found",
        old_provider_session_id="cursor-abc",
        phase_action_id="action-1",
    )
    emit_session_replaced(
        store,
        run_id,
        phase=PLANNING,
        role="planner",
        old_session_instance_id="tdp-session-a1",
        new_session_instance_id="tdp-session-b2",
        generation=2,
        reason="provider_session_not_found",
        old_provider_session_id="cursor-abc",
        new_provider_session_id="cursor-xyz",
        phase_action_id="action-1",
    )
    emit_session_resume_failed(
        store,
        run_id,
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-a1",
        generation=1,
        reason="provider_session_not_found",
        provider_session_id="cursor-abc",
        phase_action_id="action-1",
    )
    emit_session_replacement_failed(
        store,
        run_id,
        phase=PLANNING,
        role="planner",
        session_instance_id="tdp-session-b2",
        generation=2,
        reason="provider_unavailable",
        phase_action_id="action-1",
    )

    types = {event["type"] for event in store.load_events(run_id)}
    assert SESSION_REPLACEMENT_STARTED in types
    assert SESSION_REPLACED in types
    assert SESSION_RESUME_FAILED in types
    assert SESSION_REPLACEMENT_FAILED in types


def test_commit_primary_provider_session_binding_emits_lineage_event(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    _create_planning_run(store)

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id="cursor-planner-01",
        provider="cursor",
    )

    events = [event for event in store.load_events(run_id) if event.get("type") == SESSION_PROVIDER_ID_BOUND]
    assert len(events) == 1
    event = events[0]
    assert event["role"] == "planner"
    assert event["provider_session_id"] == "cursor-planner-01"
    assert event["session_instance_id"].startswith("tdp-session-")


def test_sync_persisted_session_id_emits_lineage_event(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    _create_planning_run(store)

    provider = MagicMock()
    provider.canonical_session_id.return_value = "cursor-planner-02"

    sync_persisted_session_id(
        provider,
        store,
        run_id,
        "cursor-planner-02",
        field="primary_planner_session_id",
    )

    events = [event for event in store.load_events(run_id) if event.get("type") == SESSION_PROVIDER_ID_BOUND]
    assert len(events) == 1
    assert events[0]["provider_session_id"] == "cursor-planner-02"


def test_commit_reviewer_loop_provider_session_emits_lineage_event(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    _create_planning_run(store, run_id)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run(run_id, run, expected_revision)

    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=None,
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        lifecycle_status="review_pending",
        active_stage=None,
        finding_set_id="review-whole-plan-01-fs-01",
        revise_at="major",
    )
    updated = loop.with_reviewer_provider_session_id("cursor-reviewer-01")
    commit_reviewer_loop_provider_session(store, run_id, updated)

    events = [event for event in store.load_events(run_id) if event.get("type") == SESSION_PROVIDER_ID_BOUND]
    assert len(events) == 1
    event = events[0]
    assert event["role"] == "reviewer"
    assert event["loop_id"] == loop.id
    assert event["provider_session_id"] == "cursor-reviewer-01"
