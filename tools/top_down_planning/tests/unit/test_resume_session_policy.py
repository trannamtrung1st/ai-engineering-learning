"""Resume continuation session policy tests (§21 test 37 / RR-SESSION-06)."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    SessionBinding,
    new_session_binding,
)
from top_down_planning.orchestrator.capability import issue_session_capability
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.orchestrator.session_policy_execution import (
    derive_session_policy,
    execute_session_policy,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
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


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T006001-006001") -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def _set_planner_starting_binding(store: FileRunStore, run_id: str) -> SessionBinding:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    binding = new_session_binding(role="planner", kind="primary", state="starting")
    binding = binding.with_provider_session_id(
        "cursor-pending-crash",
        provider="cursor",
        allow_transient=True,
    )
    run = dict(run)
    run["revision"] = expected_revision + 1
    sessions = dict(run.get("sessions") or {})
    sessions[PRIMARY_PLANNER_SLOT] = binding.to_dict()
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    return binding


def test_derive_session_policy_detects_stale_starting_binding(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    binding = _set_planner_starting_binding(store, run_id)

    run = store.load_run(run_id)
    policy = derive_session_policy(run, store.list_reviews(run_id))

    assert policy["requires_correction"] is True
    entry = policy["bindings"][PRIMARY_PLANNER_SLOT]
    assert entry["action"] == "clear_stale_starting"
    assert entry["session_instance_id"] == binding.session_instance_id
    assert entry["generation"] == binding.generation


def test_stale_starting_binding_cleared_on_resume_continuation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    binding = _set_planner_starting_binding(store, run_id)
    issue_session_capability(
        store,
        run_id,
        role="planner",
        phase=PLANNING,
        session_id="cursor-pending-crash",
        session_kind="primary",
    )
    token_id = store.list_capabilities(run_id)[0]["id"]

    run = store.load_run(run_id)
    policy = derive_session_policy(run, store.list_reviews(run_id))
    execute_session_policy(store, run_id, policy)

    updated_binding = get_primary_binding(store.load_run(run_id), "planner")
    assert updated_binding is not None
    assert updated_binding.state == "starting"
    assert updated_binding.generation == binding.generation + 1
    assert updated_binding.provider_session_id is None

    record = store.load_capability(run_id, str(token_id))
    assert record["revoked"] is True


def test_derive_session_policy_includes_resume_then_replace_for_bound_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    binding = new_session_binding(role="planner", kind="primary", state="starting")
    binding = binding.with_provider_session_id(
        "cursor-abc123",
        provider="cursor",
    )
    run = dict(run)
    run["revision"] = expected_revision + 1
    sessions = dict(run.get("sessions") or {})
    sessions[PRIMARY_PLANNER_SLOT] = binding.to_dict()
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)

    policy = derive_session_policy(store.load_run(run_id), store.list_reviews(run_id))

    assert policy["requires_correction"] is False
    entry = policy["bindings"][PRIMARY_PLANNER_SLOT]
    assert entry["action"] == "resume_then_replace_if_missing"
    assert entry["provider_session_id"] == "cursor-abc123"
    assert entry["role"] == "planner"


def test_prepare_resume_includes_session_policy_for_starting_binding(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    _set_planner_starting_binding(store, run_id)

    run = store.load_run(run_id)
    run = dict(run)
    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "provider_unavailable",
        "category": "operational",
        "phase": PLANNING,
        "message": "interrupted",
    }
    store.save_run(run_id, run, expected_revision)

    resume_plan = prepare_resume(
        store,
        run_id,
        store.load_resolved_config(run_id),
    )
    assert resume_plan.session_policy["requires_correction"] is True
