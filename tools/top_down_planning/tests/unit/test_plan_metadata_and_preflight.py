"""Tests for plan metadata seeding, update_plan, and candidate preflight."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService
from top_down_planning.cli.user import _initial_plan
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.mutations import apply_operations
from top_down_planning.domain.validators import validate_plan
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import create_run_kwargs, done_events, script_planning_candidate_ready


def test_initial_plan_seeds_boundaries_and_acceptance() -> None:
    config = {
        "run": {
            "input_refs": ["a.md"],
            "boundaries": ["Stay in tools/"],
            "acceptance": ["Tests pass"],
        }
    }
    plan = _initial_plan("run-x", config, output_goal="Goal.")
    assert plan.boundaries == ["Stay in tools/"]
    assert plan.acceptance == ["Tests pass"]
    assert plan.risks == []
    assert plan.scope.includes == []
    assert plan.scope.excludes == []
    assert plan.constraints == []
    assert plan.assumptions == []
    root = plan.items["item-root"]
    assert root.kind == "aggregate"
    assert root.risks == []
    assert root.source_refs == []


def test_update_plan_advances_revision_and_metadata() -> None:
    plan = Plan(
        id="plan-meta",
        revision=2,
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
    result = apply_operations(
        plan,
        2,
        [
            {
                "op": "update_plan",
                "patch": {
                    "boundaries": ["b1"],
                    "acceptance": ["a1"],
                    "constraints": ["c1"],
                    "assumptions": ["assume"],
                    "scope": {"includes": ["src/"], "excludes": []},
                },
            }
        ],
    )
    assert result.revision == 3
    assert result.plan.boundaries == ["b1"]
    assert result.plan.acceptance == ["a1"]
    assert result.plan.constraints == ["c1"]
    assert result.plan.assumptions == ["assume"]
    assert result.plan.scope.includes == ["src/"]


def test_plan_snapshot_exposes_metadata(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-snap",
        revision=0,
        output_goal="Goal.",
        boundaries=["bound"],
        acceptance=["accept"],
        risks=["Delivery risk."],
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
                risks=["Item risk."],
                source_refs=["spec.md → Section"],
            )
        },
    )
    store.create_run(
        "run-20260101T000701-000701",
        plan=plan,
        **create_run_kwargs(store.root),
        phase=PLANNING,
    )
    snapshot = PlanAgentService(store, "run-20260101T000701-000701").snapshot()
    assert snapshot["boundaries"] == ["bound"]
    assert snapshot["acceptance"] == ["accept"]
    assert snapshot["risks"] == ["Delivery risk."]
    assert "constraints" in snapshot
    assert "assumptions" in snapshot
    assert "scope" in snapshot
    root_item = next(item for item in snapshot["items"] if item["id"] == "item-root")
    assert root_item["risks"] == ["Item risk."]
    assert root_item["source_refs"] == ["spec.md → Section"]


def test_candidate_preflight_rejects_invalid_plan(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-bad",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="",
                kind="aggregate",
            )
        },
    )
    store.create_run(
        "run-20260101T000702-000702",
        plan=plan,
        **create_run_kwargs(store.root),
        phase=PLANNING,
    )
    orch = PlanningPhaseOrchestrator(
        store, "run-20260101T000702-000702", StubProvider()
    )
    preflight = orch._candidate_preflight()
    assert preflight.ok is False
    assert any(issue.code == "missing_required_field" for issue in preflight.issues)


def test_candidate_preflight_blocks_transition_for_invalid_plan(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-bad",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="",
                kind="aggregate",
            )
        },
    )
    config = create_run_kwargs(store.root)["resolved_config"]
    assert isinstance(config, dict)
    config = dict(config)
    limits = dict(config.get("limits") or {})
    planning_limits = dict(limits.get("planning") or {})
    planning_limits["max_agent_turns"] = 2
    limits["planning"] = planning_limits
    config["limits"] = limits
    store.create_run(
        "run-20260101T000704-000704",
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PLANNING,
    )
    provider = StubProvider()
    provider.script_turn(done_events(signal="candidate_plan_ready", text="ready"))
    provider.script_turn(done_events(text="continue after preflight"))
    result = PlanningPhaseOrchestrator(
        store, "run-20260101T000704-000704", provider
    ).run()
    assert store.load_run("run-20260101T000704-000704")["phase"] == PLANNING
    assert result.ok is False
    assert result.outcome == "blocked" or "max_agent_turns" in (result.reason or "")


def test_valid_candidate_still_enters_whole_plan_review(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-ok",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000000",
                title="Work",
                outcome="Done.",
                acceptance=["ok"],
                kind="work",
            ),
        },
    )
    store.create_run(
        "run-20260101T000703-000703",
        plan=plan,
        **create_run_kwargs(store.root),
        phase=PLANNING,
    )
    provider = StubProvider()
    provider.script_turn(done_events(signal="candidate_plan_ready", text="ready"))
    result = PlanningPhaseOrchestrator(
        store, "run-20260101T000703-000703", provider
    ).run()
    assert result.ok is True
    assert store.load_run("run-20260101T000703-000703")["phase"] == "whole_plan_review"


def test_candidate_preflight_surfaces_warnings_without_blocking(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    plan = Plan(
        id="plan-warn",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                outcome="Root outcome.",
                acceptance=["root ok"],
                kind="aggregate",
            ),
            "item-parent": PlanItem(
                id="item-parent",
                parent_id="item-root",
                order_key="0000000000",
                title="Parent work",
                outcome="Parent outcome.",
                acceptance=["parent ok"],
                kind="work",
            ),
            "item-child": PlanItem(
                id="item-child",
                parent_id="item-parent",
                order_key="0000000000",
                title="Child work",
                outcome="Child outcome.",
                acceptance=["child ok"],
                kind="work",
            ),
        },
    )
    store.create_run(
        "run-20260101T000705-000705",
        plan=plan,
        **create_run_kwargs(store.root),
        phase=PLANNING,
    )
    provider = StubProvider()
    script_planning_candidate_ready(provider)
    result = PlanningPhaseOrchestrator(
        store, "run-20260101T000705-000705", provider
    ).run()
    assert result.ok is True
    assert store.load_run("run-20260101T000705-000705")["phase"] == "whole_plan_review"
    events = store.load_events("run-20260101T000705-000705")
    ready_events = [
        event
        for event in events
        if event["type"] == "planning_candidate_ready"
    ]
    assert len(ready_events) == 1
    assert any(
        "executable descendants" in warning
        for warning in ready_events[0].get("warnings") or []
    )


def test_draft_validation_ok_for_titled_plan() -> None:
    plan = Plan(
        id="plan-ok",
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
    assert validate_plan(plan).ok is True
