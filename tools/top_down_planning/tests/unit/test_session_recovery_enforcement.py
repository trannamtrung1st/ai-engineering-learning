"""Session recovery enforcement tests (proposal §21 tests 31–34, 38–39, 41)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_recovery_state import (
    domain_budget_committed_for_phase_action,
    replacement_attempted_for_phase_action,
)
from top_down_planning.orchestrator.session_recovery_enforcement import (
    record_phase_action_domain_commit,
    record_session_replacement_attempt,
)
from top_down_planning.orchestrator import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.errors import SessionRecoveryExhausted
from top_down_planning.orchestrator.planning import build_planner_context_manifest
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    consume_provider_turn_with_session_recovery,
    ensure_phase_action_id,
)
from top_down_planning.orchestrator.session_events import commit_primary_provider_session_binding
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import update_primary_binding
from core_tools.provider import StubProvider
from tests.helpers import create_run_kwargs, done_events, grant_capability, minimal_resolved_config


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


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T007101-007101") -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def _bind_planner(store: FileRunStore, run_id: str, session_id: str) -> None:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = update_primary_binding(
        dict(run.get("sessions") or {}),
        role="planner",
        provider_session_id=session_id,
        provider="cursor",
    )
    store.save_run(run_id, run, expected_revision)


def test_missing_session_attempt_consumes_no_domain_budget(tmp_path: Path) -> None:
    """§21 test 31: not-found resume attempt does not commit domain budget."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_planner(store, run_id, session_id)

    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="replacement turn"))
    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    run = store.load_run(run_id)
    assert run["planning"]["agent_turns"] == 1


def test_replacement_first_turn_commits_domain_budget_once(tmp_path: Path) -> None:
    """§21 test 32: replacement path commits planning budget exactly once."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_planner(store, run_id, session_id)

    phase_action_id = ensure_phase_action_id(store, run_id)
    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement start"))
    provider.script_turn(done_events(text="replacement turn"))
    outcome = consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=frozenset({"candidate_plan_ready"}),
        recovery=build_planner_turn_recovery(
            store,
            run_id,
            phase="planning",
            expected_next_action="continue planning",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
        ),
    )

    assert outcome.replaced is True
    assert outcome.domain_budget_committed is True
    run = store.load_run(run_id)
    assert domain_budget_committed_for_phase_action(run, phase_action_id)
    assert run["phase_action_id"] is None


def test_replacement_attempted_only_once_per_phase_action_id(tmp_path: Path) -> None:
    """§21 test 33: second not-found for the same phase_action_id is refused."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    phase_action_id = ensure_phase_action_id(store, run_id)
    record_session_replacement_attempt(store, run_id, phase_action_id)
    run = store.load_run(run_id)
    assert replacement_attempted_for_phase_action(run, phase_action_id)

    provider = StubProvider()
    provider.mark_session_not_found("stub-session-missing")
    with pytest.raises(SessionRecoveryExhausted):
        consume_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            "stub-session-missing",
            allowed_signals=frozenset(),
            recovery=build_planner_turn_recovery(
                store,
                run_id,
                phase="planning",
                expected_next_action="continue planning",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "session_recovery_exhausted"


def test_replacement_session_also_missing_fails_run(tmp_path: Path) -> None:
    """§21 test 34: replacement session missing marks run session_recovery_exhausted."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_planner(store, run_id, session_id)

    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement start"))
    provider.mark_session_not_found("stub-session-2")
    with pytest.raises(SessionRecoveryExhausted):
        consume_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            session_id,
            allowed_signals=frozenset(),
            recovery=build_planner_turn_recovery(
                store,
                run_id,
                phase="planning",
                expected_next_action="continue planning",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "session_recovery_exhausted"


def test_provider_id_binding_commit_is_idempotent(tmp_path: Path) -> None:
    """§21 test 38: rebinding the same durable provider id is a no-op."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    _bind_planner(store, run_id, "cursor-session-1")
    before_revision = int(store.load_run(run_id)["revision"])
    events_before = len(store.load_events(run_id))

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id="cursor-session-1",
        phase_action_id="action-bind-1",
    )

    run = store.load_run(run_id)
    assert int(run["revision"]) == before_revision
    assert len(store.load_events(run_id)) == events_before


def test_domain_commit_is_idempotent_for_phase_action(tmp_path: Path) -> None:
    """§21 test 39 replacement-path: domain commit happens once per phase_action_id."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    phase_action_id = ensure_phase_action_id(store, run_id)

    assert record_phase_action_domain_commit(store, run_id, phase_action_id) is True
    revision_after_first = int(store.load_run(run_id)["revision"])
    assert record_phase_action_domain_commit(store, run_id, phase_action_id) is False
    assert int(store.load_run(run_id)["revision"]) == revision_after_first


def test_stale_capabilities_revoked_on_replacement(tmp_path: Path) -> None:
    """§21 test 41: replacement revokes capabilities for the stale binding generation."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_planner(store, run_id, session_id)
    token = grant_capability(
        store,
        run_id,
        role="planner",
        phase="planning",
        session_id=session_id,
    )
    token_id = store.list_capabilities(run_id)[0]["id"]

    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement start"))
    provider.script_turn(done_events(text="replacement turn"))
    consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=frozenset(),
        recovery=build_planner_turn_recovery(
            store,
            run_id,
            phase="planning",
            expected_next_action="continue planning",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
        ),
    )

    record = store.load_capability(run_id, str(token_id))
    assert record["revoked"] is True
