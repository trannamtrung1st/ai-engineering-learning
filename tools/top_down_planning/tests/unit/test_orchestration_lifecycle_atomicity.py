"""ORCH-012 lifecycle state/event atomic CommitSpec regressions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import PlanningPhaseOrchestrator, ProductionPhaseOrchestrator
from top_down_planning.orchestrator.phases import PLANNING, PLAN_VALIDATED, PRODUCTION, WHOLE_OUTPUT_REVIEW, WHOLE_PLAN_REVIEW
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
