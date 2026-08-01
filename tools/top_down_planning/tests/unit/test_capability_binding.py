"""Capability binding to internal session identity tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.capability import issue_session_capability
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import bump_primary_binding_generation
from tests.helpers import create_run_kwargs, grant_capability, minimal_resolved_config


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T005001-005001") -> None:
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
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def test_capability_record_includes_session_instance_id_and_generation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005001-005001"
    _create_planning_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING, session_id="planner-sess")
    token_id = token.split(".", 1)[0]
    record = store.load_capability(run_id, token_id)
    assert record["session_instance_id"].startswith("tdp-session-")
    assert int(record["generation"]) == 1
    assert record["session_id"] == "planner-sess"


def test_generation_change_revokes_prior_capabilities(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005002-005002"
    _create_planning_run(store, run_id)

    first = grant_capability(store, run_id, role="planner", phase=PLANNING, session_id="planner-sess")
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["sessions"] = bump_primary_binding_generation(dict(run.get("sessions") or {}), role="planner")
    store.save_run(run_id, run, expected)

    second = issue_session_capability(
        store,
        run_id,
        role="planner",
        phase=PLANNING,
        session_id="planner-sess",
    )
    first_id = first.split(".", 1)[0]
    second_id = second.split(".", 1)[0]
    assert store.load_capability(run_id, first_id)["revoked"] is True
    assert store.load_capability(run_id, second_id)["revoked"] is False
    assert int(store.load_capability(run_id, second_id)["generation"]) == 2


def test_authorize_rejects_stale_generation_capability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005003-005003"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING, session_id="planner-sess")

    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["sessions"] = bump_primary_binding_generation(dict(run.get("sessions") or {}), role="planner")
    store.save_run(run_id, run, expected)

    with pytest.raises(CapabilityDeniedError, match="session"):
        authorize_mutation(store, run_id, operation="plan_apply", capability_token=token)


def test_capability_record_persisted_to_disk_with_binding_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005004-005004"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    path = store.capabilities_dir(run_id) / f"{token_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["session_instance_id"].startswith("tdp-session-")
    assert "generation" in payload
