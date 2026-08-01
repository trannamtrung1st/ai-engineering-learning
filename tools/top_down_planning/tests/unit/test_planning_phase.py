"""Unit tests for the planning-phase orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import PlanningPhaseOrchestrator, ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    assert_primary_session_id,
    create_run_kwargs,
    done_events,
    grant_capability,
    minimal_resolved_config,
    plan_root_item,
    sessions_with_primary_session,
    with_root_contract,
)


def _create_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000101-000101",
    *,
    limits: dict | None = None,
) -> None:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
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
        "limits": {
            "planning": {
                "max_items_added": 20,
                "max_agent_turns": 40,
            }
        },
    }
    if limits:
        config["limits"]["planning"].update(limits)

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
    )


def test_planning_phase_reaches_candidate_ready_with_apply_path(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()

    run_id = "run-20260101T000101-000101"
    provider.script_turn(done_events(text="planner session start"))
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
                        "temp_id": "item-api",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {"kind": "work", "title": "API", "outcome": "API exists."},
                    },
                    {
                        "op": "add_item",
                        "temp_id": "item-ui",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {"kind": "work", "title": "UI", "outcome": "UI exists."},
                    },
                ]
            ),
        ),
    )

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.outcome is None
    assert result.session_id is not None
    assert result.agent_turns == 2
    assert result.items_added == 2

    plan = store.load_plan_model("run-20260101T000101-000101")
    assert len(plan.items) == 3

    run = store.load_run("run-20260101T000101-000101")
    assert_primary_session_id(run, "planner", result.session_id)
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert run["outcome"] is None

    events = store.load_events("run-20260101T000101-000101")
    started = [event for event in events if event["type"] == "planner_session_started"]
    assert started
    assert started[0]["model"] == "auto"
    assert any(event["type"] == "planning_candidate_ready" for event in events)


def test_planning_turn_limit_yields_blocked_not_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, limits={"max_agent_turns": 1})
    provider = StubProvider()
    provider.script_turn(done_events(signal="continue", text="planning turn"))

    result = PlanningPhaseOrchestrator(store, "run-20260101T000101-000101", provider).run()

    assert result.ok is False
    assert result.outcome is None
    assert result.reason is not None
    assert "max_agent_turns" in result.reason

    run = store.load_run("run-20260101T000101-000101")
    assert run["outcome"] is None
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "limit_exhausted"
    assert run["phase"] == PLANNING


def test_resume_planning_keeps_same_session_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()

    run = store.load_run("run-20260101T000101-000101")
    config = store.load_resolved_config("run-20260101T000101-000101")
    from top_down_planning.orchestrator.planning import build_planner_context_manifest

    plan = store.load_plan_model("run-20260101T000101-000101")
    provider.script_turn(done_events(signal="continue", text="planning turn"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest("run-20260101T000101-000101", run, config, plan),
    )
    list(provider.stream_events(session_id))

    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    run["sessions"] = sessions_with_primary_session(planner=session_id)
    run["planning"] = {"agent_turns": 1, "items_added": 0}
    store.save_run("run-20260101T000101-000101", run, expected_revision)

    provider.script_turn(done_events(signal="candidate_plan_ready", text="planning turn"))
    result = PlanningPhaseOrchestrator(store, "run-20260101T000101-000101", provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.session_id == session_id
    assert result.agent_turns == 2
    assert provider.get_session_reference(session_id)["turn_count"] == 2


def test_planning_resumes_persisted_session_on_fresh_provider(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()
    provider.script_turn(done_events(signal="continue", text="planning turn"))
    run = store.load_run("run-20260101T000101-000101")
    config = store.load_resolved_config("run-20260101T000101-000101")
    from top_down_planning.orchestrator.planning import build_planner_context_manifest

    plan = store.load_plan_model("run-20260101T000101-000101")
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest("run-20260101T000101-000101", run, config, plan),
    )
    list(provider.stream_events(session_id))

    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    run["sessions"] = sessions_with_primary_session(planner=session_id)
    run["planning"] = {"agent_turns": 1, "items_added": 0}
    store.save_run("run-20260101T000101-000101", run, expected_revision)

    fresh_provider = StubProvider()
    fresh_provider.script_session_turn(
        session_id,
        done_events(signal="candidate_plan_ready", text="done"),
    )
    result = PlanningPhaseOrchestrator(
        store,
        "run-20260101T000101-000101",
        fresh_provider,
    ).run()

    assert result.ok is True
    resumed = [
        event
        for event in store.load_events("run-20260101T000101-000101")
        if event["type"] == "planner_session_resumed"
    ]
    assert resumed
    assert resumed[-1]["model"] == "auto"


def test_non_planner_apply_during_planning_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    service = PlanAgentService(store, "run-20260101T000101-000101")
    token = grant_capability(store, "run-20260101T000101-000101", role="producer", phase=PLANNING)

    with pytest.raises(CapabilityDeniedError):
        service.apply(
            {
                "base_revision": 0,
                "operations": [
                    {
                        "op": "add_item",
                        "temp_id": "item-x",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {"kind": "work", "title": "X"},
                    }
                ],
            },
            capability_token=token,
        )


def test_orchestrator_uses_plan_applied_before_candidate_ready(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()
    provider.script_turn(done_events(signal="candidate_plan_ready", text="planning turn"))

    service = PlanAgentService(store, "run-20260101T000101-000101")
    service.apply(
        {
            "base_revision": 0,
            "operations": with_root_contract(
                [
                    {
                        "op": "add_item",
                        "temp_id": "item-a",
                        "parent_id": "item-root",
                        "placement": {"last_child": True},
                        "item": {"kind": "work", "title": "A"},
                    }
                ]
            ),
        },
        capability_token=grant_capability(store, "run-20260101T000101-000101", role="planner", phase=PLANNING),
    )

    from top_down_planning.domain.session_bindings import PRIMARY_PLANNER_SLOT, new_session_binding
    from top_down_planning.persistence.session_bindings import coerce_structured_sessions

    run = store.load_run("run-20260101T000101-000101")
    sessions = coerce_structured_sessions(run.get("sessions"))
    sessions[PRIMARY_PLANNER_SLOT] = new_session_binding(
        role="planner",
        kind="primary",
        state="unbound",
    ).to_dict()
    run = dict(run)
    run["sessions"] = sessions
    expected = int(run["revision"])
    run["revision"] = expected + 1
    store.save_run("run-20260101T000101-000101", run, expected)

    result = PlanningPhaseOrchestrator(store, "run-20260101T000101-000101", provider).run()
    assert result.ok is True
    assert len(store.load_plan_model("run-20260101T000101-000101").items) == 2
