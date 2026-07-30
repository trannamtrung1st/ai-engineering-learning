"""Unit tests for the planning-phase orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import PlanningPhaseOrchestrator, ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import done_events


def _create_run(
    store: FileRunStore,
    run_id: str = "run-planning",
    *,
    limits: dict | None = None,
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
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
                "max_expansion_iterations": 20,
                "max_agent_turns": 40,
            }
        },
        "provider": {"name": "stub"},
    }
    if limits:
        config["limits"]["planning"].update(limits)

    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest="input-a",
        output_goal_digest="goal-b",
        context_digest="0" * 64,
        workspace=str(store.root),
    )


def test_planning_phase_reaches_candidate_ready_with_apply_path(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()

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
                            "temp_id": "item-api",
                            "parent_id": "item-root",
                            "placement": {"last_child": True},
                            "item": {"title": "API", "outcome": "API exists."},
                        },
                        {
                            "op": "add_item",
                            "temp_id": "item-ui",
                            "parent_id": "item-root",
                            "placement": {"last_child": True},
                            "item": {"title": "UI", "outcome": "UI exists."},
                        },
                    ],
                },
            },
            *done_events(signal="candidate_plan_ready", text="planning turn"),
        ]
    )

    result = PlanningPhaseOrchestrator(store, "run-planning", provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.outcome is None
    assert result.session_id is not None
    assert result.agent_turns == 1
    assert result.expansion_iterations == 2

    plan = store.load_plan_model("run-planning")
    assert len(plan.items) == 3

    run = store.load_run("run-planning")
    assert run["sessions"]["primary_planner_session_id"] == result.session_id
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert run["outcome"] is None

    events = store.load_events("run-planning")
    assert any(event["type"] == "planner_session_started" for event in events)
    assert any(event["type"] == "planning_candidate_ready" for event in events)


def test_planning_turn_limit_yields_blocked_not_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, limits={"max_agent_turns": 1})
    provider = StubProvider()
    provider.script_turn(done_events(signal="continue", text="planning turn"))

    result = PlanningPhaseOrchestrator(store, "run-planning", provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "max_agent_turns" in result.reason

    run = store.load_run("run-planning")
    assert run["outcome"] == "blocked"
    assert run["status"] == "completed"
    assert run["phase"] == PLANNING


def test_resume_planning_keeps_same_session_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()

    run = store.load_run("run-planning")
    config = store.load_resolved_config("run-planning")
    from top_down_planning.orchestrator.planning import build_planner_context_manifest

    plan = store.load_plan_model("run-planning")
    provider.script_turn(done_events(signal="continue", text="planning turn"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest("run-planning", run, config, plan),
    )
    list(provider.stream_events(session_id))

    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_planner_session_id": session_id}
    run["planning"] = {"agent_turns": 1, "expansion_iterations": 0}
    store.save_run("run-planning", run, expected_revision)

    provider.script_turn(done_events(signal="candidate_plan_ready", text="planning turn"))
    result = PlanningPhaseOrchestrator(store, "run-planning", provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.session_id == session_id
    assert result.agent_turns == 2
    assert provider.get_session_reference(session_id)["turn_count"] == 2


def test_non_planner_apply_during_planning_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()
    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "plan_apply",
                "role": "producer",
                "request": {
                    "base_revision": 0,
                    "operations": [
                        {
                            "op": "add_item",
                            "temp_id": "item-x",
                            "parent_id": "item-root",
                            "placement": {"last_child": True},
                            "item": {"title": "X"},
                        }
                    ],
                },
            },
            *done_events(signal="candidate_plan_ready", text="planning turn"),
        ]
    )

    with pytest.raises(ProviderRunError, match="role=planner"):
        PlanningPhaseOrchestrator(store, "run-planning", provider).run()


def test_orchestrator_uses_plan_applied_before_candidate_ready(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    provider = StubProvider()
    provider.script_turn(done_events(signal="candidate_plan_ready", text="planning turn"))

    service = PlanAgentService(store, "run-planning")
    service.apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "add_item",
                    "temp_id": "item-a",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"title": "A"},
                }
            ],
        },
        role="planner",
    )

    result = PlanningPhaseOrchestrator(store, "run-planning", provider).run()
    assert result.ok is True
    assert len(store.load_plan_model("run-planning").items) == 2
