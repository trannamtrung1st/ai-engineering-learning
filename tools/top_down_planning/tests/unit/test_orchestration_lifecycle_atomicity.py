"""ORCH-012 lifecycle state/event atomic CommitSpec regressions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.orchestrator import (
    PlanAmendmentOrchestrator,
    PlanningPhaseOrchestrator,
    ProductionPhaseOrchestrator,
)
from top_down_planning.orchestrator.phases import (
    PLANNING,
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.provider_turns import ensure_phase_action_id
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    create_run_kwargs,
    done_events,
    grant_capability,
    minimal_resolved_config,
    plan_root_item,
    with_root_contract,
)


def _planning_store(
    tmp_path: Path,
    *,
    limits: dict | None = None,
) -> tuple[FileRunStore, str]:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020001-020001"
    root = plan_root_item(title="Deliver", outcome="Deliver.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": ["README.md"]},
        "planning": {"stop_hint": "Stop.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {
            "planning": {"max_items_added": 20, "max_agent_turns": 40},
            "production": {"max_batches": 10, "max_agent_turns_per_batch": 5},
        },
    }
    if limits:
        config["limits"]["planning"].update(limits)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    return store, run_id


def _events_with_types(store: FileRunStore, run_id: str, types: set[str]) -> list[dict]:
    return [event for event in store.load_events(run_id) if event.get("type") in types]


def _shared_txn_id(events: list[dict]) -> bool:
    txn_ids = {event.get("txn_id") for event in events if event.get("txn_id")}
    return len(txn_ids) == 1 and len(events) > 0


def test_planning_limit_pause_and_semantic_event_share_commit_txn(tmp_path: Path) -> None:
    store, run_id = _planning_store(tmp_path, limits={"max_items_added": 1})
    provider = StubProvider()
    provider.script_turn(
        done_events(signal="candidate_plan_ready", text="planning turn"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=with_root_contract(
                [
                    {
                        "op": "add_item",
                        "temp_id": "item-a",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {"kind": "work", "title": "A"},
                    },
                    {
                        "op": "add_item",
                        "temp_id": "item-b",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {"kind": "work", "title": "B"},
                    },
                ]
            ),
        ),
    )
    result = PlanningPhaseOrchestrator(store, run_id, provider).run()
    assert result.ok is False

    limit_events = _events_with_types(
        store,
        run_id,
        {"run_paused", "planning_limit_exceeded"},
    )
    assert len(limit_events) == 2
    assert _shared_txn_id(limit_events)


def test_planning_completion_phase_and_event_share_commit_txn(tmp_path: Path) -> None:
    store, run_id = _planning_store(tmp_path)
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()
    assert result.ok is True
    assert store.load_run(run_id)["phase"] == WHOLE_PLAN_REVIEW

    ready_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "planning_candidate_ready"
    ]
    assert len(ready_events) == 1
    assert ready_events[0].get("txn_id")


def test_production_phase_entry_event_shares_commit_txn(tmp_path: Path) -> None:
    from tests.helpers import whole_plan_approval_record

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020002-020002"
    config = minimal_resolved_config()
    plan = Plan(
        id=f"plan-{run_id}",
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
        phase=PLAN_VALIDATED,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    orch = ProductionPhaseOrchestrator(store, run_id, StubProvider())
    run = orch._enter_production_phase()
    assert run["phase"] == PRODUCTION

    started = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "production_phase_started"
    ]
    assert len(started) == 1
    assert started[0].get("txn_id")


def test_planning_completion_preserves_capabilities_when_commit_fails(tmp_path: Path) -> None:
    store, run_id = _planning_store(tmp_path)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    with patch.object(store, "commit", side_effect=OSError("lifecycle cas failed")):
        with pytest.raises(OSError, match="lifecycle cas failed"):
            PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert store.load_run(run_id)["phase"] == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False


def test_planning_completion_crash_during_replace_restores_prior_phase(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    store, run_id = _planning_store(tmp_path)
    revision_before = int(store.load_run(run_id)["revision"])
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            PlanningPhaseOrchestrator(store, run_id, provider).run()

    run_after = store.load_run(run_id)
    assert run_after["phase"] == PLANNING
    assert int(run_after["revision"]) == revision_before
    ready_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "planning_candidate_ready"
    ]
    assert ready_events == []


def test_observing_store_commit_swallows_observability_emit_failure(tmp_path: Path) -> None:
    from core_tools.observability import NullSink
    from top_down_planning.observability import ObservabilityContext, wrap_store_with_observability

    raw_store, run_id = _planning_store(tmp_path)
    observability = ObservabilityContext(sink=NullSink(), run_id=run_id)

    def fail_emit(_event: object) -> None:
        raise RuntimeError("emit failed")

    observability.emit = fail_emit  # type: ignore[method-assign]
    store = wrap_store_with_observability(raw_store, observability)
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()
    assert result.ok is True
    assert raw_store.load_run(run_id)["phase"] == WHOLE_PLAN_REVIEW


def test_planning_completion_ok_when_post_commit_revoke_fails(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.run_transitions import pending_capability_revoke_phase

    store, run_id = _planning_store(tmp_path)
    grant_capability(store, run_id, role="planner", phase=PLANNING)
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert pending_capability_revoke_phase(run) == PLANNING


def test_reconcile_pending_revoke_failure_preserves_marker_and_capabilities(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.run_transitions import (
        pending_capability_revoke_phase,
        reconcile_pending_capability_revocation,
    )

    store, run_id = _planning_store(tmp_path)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase"] = WHOLE_PLAN_REVIEW
    updated["pending_capability_revoke_phase"] = PLANNING
    store.save_run(run_id, updated, expected_revision)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        reconcile_pending_capability_revocation(store, run_id)

    run_after = store.load_run(run_id)
    assert run_after["phase"] == WHOLE_PLAN_REVIEW
    assert run_after["status"] == "running"
    assert pending_capability_revoke_phase(run_after) == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False

    reconcile_pending_capability_revocation(store, run_id)
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert store.load_capability(run_id, token_id)["revoked"] is True


def _production_store_at_plan_validated(
    tmp_path: Path,
    *,
    max_batches: int = 10,
    max_agent_turns_per_batch: int = 5,
) -> tuple[FileRunStore, str]:
    from tests.helpers import whole_plan_approval_record

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020003-020003"
    root = plan_root_item(title="Deliver", outcome="Deliver.")
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first},
    )
    config = minimal_resolved_config()
    config["limits"]["production"] = {
        "max_batches": max_batches,
        "max_agent_turns_per_batch": max_agent_turns_per_batch,
    }
    store.create_run(
        run_id,
        plan=plan,
        phase=PLAN_VALIDATED,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    return store, run_id


def test_production_entry_crash_during_replace_restores_prior_phase(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    store, run_id = _production_store_at_plan_validated(tmp_path)
    revision_before = int(store.load_run(run_id)["revision"])
    orch = ProductionPhaseOrchestrator(store, run_id, StubProvider())

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._enter_production_phase()

    run_after = store.load_run(run_id)
    assert run_after["phase"] == PLAN_VALIDATED
    assert int(run_after["revision"]) == revision_before
    started = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "production_phase_started"
    ]
    assert started == []


def test_production_completion_crash_during_replace_restores_prior_phase(
    tmp_path: Path,
) -> None:
    from tests.helpers import goal_met_completion_claim
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    store, run_id = _production_store_at_plan_validated(tmp_path)
    orch = ProductionPhaseOrchestrator(store, run_id, StubProvider())
    orch._enter_production_phase()

    production = store.load_production(run_id)
    production["dispositions"] = {"item-first": "completed"}
    production["batches"] = [
        {
            "id": "batch-01",
            "plan_items": ["item-first"],
            "status": "completed",
            "result": {
                "outputs": [],
                "contributions": [],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "summary": "done",
                "empty_output": False,
            },
        }
    ]
    production["output_revision"] = 1
    production["completion_claim"] = goal_met_completion_claim(
        production,
        goal_assessment="Output goal met.",
        plan_revision=0,
    )
    expected_production_revision = int(production["revision"])
    production["revision"] = expected_production_revision + 1
    store.save_production(run_id, production, expected_production_revision)

    revision_before = int(store.load_run(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._complete_production("stub-producer-session")

    run_after = store.load_run(run_id)
    assert run_after["phase"] == PRODUCTION
    assert int(run_after["revision"]) == revision_before
    completed_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "production_completed"
    ]
    assert completed_events == []

    result = orch._complete_production("stub-producer-session")
    assert result.ok is True
    assert store.load_run(run_id)["phase"] == WHOLE_OUTPUT_REVIEW
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "production_completed"
        ]
    ) == 1


def test_production_limit_crash_during_replace_retries_pause_once(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    store, run_id = _production_store_at_plan_validated(tmp_path, max_batches=1)
    orch = ProductionPhaseOrchestrator(store, run_id, StubProvider())
    orch._enter_production_phase()
    revision_before = int(store.load_run(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._pause_for_limit(
                limit="max_batches",
                message="production exceeded max_batches (1)",
                consumed=1,
                configured=1,
                session_id="stub-producer-session",
            )

    run_after = store.load_run(run_id)
    assert run_after["status"] == "running"
    assert run_after["phase"] == PRODUCTION
    assert int(run_after["revision"]) == revision_before
    assert [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "run_paused"
    ] == []
    assert _events_with_types(
        store,
        run_id,
        {"production_limit_exceeded"},
    ) == []

    result = orch._pause_for_limit(
        limit="max_batches",
        message="production exceeded max_batches (1)",
        consumed=1,
        configured=1,
        session_id="stub-producer-session",
    )
    assert result.ok is False
    limit_events = _events_with_types(
        store,
        run_id,
        {"run_paused", "production_limit_exceeded"},
    )
    assert len(limit_events) == 2
    assert _shared_txn_id(limit_events)


def _amendment_production_fixture(
    tmp_path: Path,
    provider: StubProvider,
) -> tuple[FileRunStore, str, str]:
    from tests.unit.test_plan_amendment import _create_run_in_production_with_sessions

    store = FileRunStore(tmp_path)
    _create_run_in_production_with_sessions(store, provider)
    run_id = "run-20260101T001901-001901"
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    ProductionAgentService(store, run_id).request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=token,
    )
    amendment_id = str(store.load_production(run_id)["pending_amendment_id"])
    return store, run_id, amendment_id


def test_amendment_entry_crash_during_replace_restores_production_state(
    tmp_path: Path,
) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    provider = StubProvider()
    store, run_id, amendment_id = _amendment_production_fixture(tmp_path, provider)
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    prior_plan = store.load_plan_model(run_id)
    run_revision_before = int(store.load_run(run_id)["revision"])
    production_revision_before = int(store.load_production(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._enter_plan_amendment_phase(amendment_id, prior_plan)

    assert store.load_run(run_id)["phase"] == PRODUCTION
    assert store.load_run(run_id)["status"] == "running"
    assert int(store.load_run(run_id)["revision"]) == run_revision_before
    assert int(store.load_production(run_id)["revision"]) == production_revision_before
    assert _events_with_types(
        store,
        run_id,
        {"run_paused", "plan_amendment_started"},
    ) == []

    run_after = orch._enter_plan_amendment_phase(amendment_id, prior_plan)
    assert run_after["phase"] == PLAN_AMENDMENT
    assert run_after["status"] == "paused"
    entry_events = _events_with_types(
        store,
        run_id,
        {"run_paused", "plan_amendment_started"},
    )
    assert len(entry_events) == 2
    assert _shared_txn_id(entry_events)


def test_amendment_activation_crash_during_replace_retries_once(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    provider = StubProvider()
    store, run_id, amendment_id = _amendment_production_fixture(tmp_path, provider)
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    prior_plan = store.load_plan_model(run_id)
    orch._enter_plan_amendment_phase(amendment_id, prior_plan)
    revision_before = int(store.load_run(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._activate_amendment_execution()

    run_after = store.load_run(run_id)
    assert run_after["status"] == "paused"
    assert run_after["phase"] == PLAN_AMENDMENT
    assert int(run_after["revision"]) == revision_before
    resumed_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "amendment_execution_resumed"
    ]
    assert resumed_events == []

    activated = orch._activate_amendment_execution()
    assert activated["status"] == "running"
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "amendment_execution_resumed"
        ]
    ) == 1


def test_amendment_to_whole_plan_review_crash_retries_transition_once(
    tmp_path: Path,
) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count
    from top_down_planning.orchestrator.run_transitions import pending_capability_revoke_phase

    provider = StubProvider()
    store, run_id, amendment_id = _amendment_production_fixture(tmp_path, provider)
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    prior_plan = store.load_plan_model(run_id)
    orch._enter_plan_amendment_phase(amendment_id, prior_plan)
    orch._activate_amendment_execution()
    revision_before = int(store.load_run(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._transition_to_whole_plan_review()

    run_after = store.load_run(run_id)
    assert run_after["phase"] == PLAN_AMENDMENT
    assert int(run_after["revision"]) == revision_before
    assert pending_capability_revoke_phase(run_after) is None
    ready_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "plan_amendment_revision_ready"
    ]
    assert ready_events == []

    transitioned = orch._transition_to_whole_plan_review()
    assert transitioned["phase"] == WHOLE_PLAN_REVIEW
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "plan_amendment_revision_ready"
        ]
    ) == 1


def test_amendment_to_production_crash_retries_transition_once(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count
    from top_down_planning.orchestrator.run_transitions import pending_capability_revoke_phase

    provider = StubProvider()
    store, run_id, amendment_id = _amendment_production_fixture(tmp_path, provider)
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    prior_plan = store.load_plan_model(run_id)
    orch._enter_plan_amendment_phase(amendment_id, prior_plan)
    orch._activate_amendment_execution()
    orch._transition_to_whole_plan_review()
    revision_before = int(store.load_run(run_id)["revision"])
    plan_revision = int(store.load_plan(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._resume_production_phase(plan_revision)

    run_after = store.load_run(run_id)
    assert run_after["phase"] == WHOLE_PLAN_REVIEW
    assert int(run_after["revision"]) == revision_before
    assert pending_capability_revoke_phase(run_after) != WHOLE_PLAN_REVIEW
    resumed_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "plan_amendment_production_resumed"
    ]
    assert resumed_events == []

    resumed = orch._resume_production_phase(plan_revision)
    assert resumed["phase"] == PRODUCTION
    assert resumed["status"] == "running"
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "plan_amendment_production_resumed"
        ]
    ) == 1


def test_amendment_limit_crash_during_replace_retries_pause_once(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    provider = StubProvider()
    store, run_id, amendment_id = _amendment_production_fixture(tmp_path, provider)
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    prior_plan = store.load_plan_model(run_id)
    orch._enter_plan_amendment_phase(amendment_id, prior_plan)
    orch._activate_amendment_execution()
    revision_before = int(store.load_run(run_id)["revision"])
    limit_events_before = len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "plan_amendment_limit_exceeded"
        ]
    )
    limit_paused_before = len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "run_paused"
            and (event.get("stop") or {}).get("code") == "limit_exhausted"
        ]
    )

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            orch._pause_for_amendment_limit(
                message="plan amendment exceeded max_revision_cycles_per_request (1)",
                limit="max_revision_cycles_per_request",
                consumed=1,
                configured=1,
                amendment_id=amendment_id,
                planner_session_id="stub-planner",
                producer_session_id="stub-producer",
            )

    run_after = store.load_run(run_id)
    assert run_after["status"] == "running"
    assert run_after["phase"] == PLAN_AMENDMENT
    assert int(run_after["revision"]) == revision_before
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "plan_amendment_limit_exceeded"
        ]
    ) == limit_events_before
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "run_paused"
            and (event.get("stop") or {}).get("code") == "limit_exhausted"
        ]
    ) == limit_paused_before

    result = orch._pause_for_amendment_limit(
        message="plan amendment exceeded max_revision_cycles_per_request (1)",
        limit="max_revision_cycles_per_request",
        consumed=1,
        configured=1,
        amendment_id=amendment_id,
        planner_session_id="stub-planner",
        producer_session_id="stub-producer",
    )
    assert result.ok is False
    run_final = store.load_run(run_id)
    assert run_final["status"] == "paused"
    assert run_final["stop"]["code"] == "limit_exhausted"

    limit_exceeded_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "plan_amendment_limit_exceeded"
    ]
    assert len(limit_exceeded_events) == 1
    success_txn = limit_exceeded_events[0].get("txn_id")
    paired_pause_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "run_paused"
        and (event.get("stop") or {}).get("code") == "limit_exhausted"
        and event.get("txn_id") == success_txn
    ]
    assert len(paired_pause_events) == 1


def test_phase_action_assignment_and_event_share_commit_txn(tmp_path: Path) -> None:
    store, run_id = _planning_store(tmp_path)
    action_id = ensure_phase_action_id(store, run_id)
    run = store.load_run(run_id)
    assert run["phase_action_id"] == action_id
    assigned = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "phase_action_assigned"
    ]
    assert len(assigned) == 1
    assert assigned[0].get("txn_id")


def test_phase_action_assignment_crash_during_replace_retries_once(tmp_path: Path) -> None:
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    store, run_id = _planning_store(tmp_path)
    revision_before = int(store.load_run(run_id)["revision"])

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            ensure_phase_action_id(store, run_id)

    run_after = store.load_run(run_id)
    assert run_after.get("phase_action_id") is None
    assert int(run_after["revision"]) == revision_before
    assigned = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "phase_action_assigned"
    ]
    assert assigned == []

    action_id = ensure_phase_action_id(store, run_id)
    assert store.load_run(run_id)["phase_action_id"] == action_id
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "phase_action_assigned"
        ]
    ) == 1
