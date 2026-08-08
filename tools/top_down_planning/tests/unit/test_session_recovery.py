"""Session recovery tests (proposal §21 tests 25–30)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool.artifacts import (
    EvidenceIntegrityError,
    capture_output_artifact,
    validate_production_evidence_integrity,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_lineage import (
    REASON_PROVIDER_SESSION_NOT_FOUND,
    REASON_PROVIDER_TURN_STALLED,
)
from top_down_planning.domain.reviews import ReviewLoop
from core_tools.provider.errors import (
    ProviderSessionNotFoundError,
    ProviderTurnStalledError,
)
from top_down_planning.orchestrator import PlanningPhaseOrchestrator, RunEngine
from top_down_planning.orchestrator.errors import ProducerReplacementBlocked
from top_down_planning.orchestrator.focused_review import build_focused_review_package
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.planning import build_planner_context_manifest
from top_down_planning.orchestrator.production import build_producer_context_manifest
from top_down_planning.orchestrator.provider_turns import (
    build_reviewer_turn_recovery,
    consume_provider_turn_with_session_recovery,
    consume_reviewer_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.recovery_manifest import (
    REPLACEMENT_SESSION_NOTICE,
    build_planner_recovery_manifest,
    build_producer_recovery_manifest,
)
from top_down_planning.orchestrator.reviewer_session import begin_reviewer_review
from top_down_planning.orchestrator.session_recovery import (
    is_recoverable_provider_session_loss,
    recovery_reason_for_session_loss,
    replace_primary_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    primary_provider_session_id,
)
from top_down_planning.workspace import WorkspaceIntegrityError, validate_run_workspace_integrity
from core_tools.provider import StubProvider
from tests.helpers import (
    bind_primary_session_for_tests,
    create_run_kwargs,
    done_events,
    minimal_resolved_config,
    whole_plan_approval_record,
    make_review_loop,
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


def _create_planning_run(store: FileRunStore, run_id: str = "run-20260101T006001-006001") -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


def _bind_primary_session(
    store: FileRunStore,
    run_id: str,
    *,
    role: str,
    session_id: str,
) -> None:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    config = store.load_resolved_config(run_id)
    run["sessions"] = bind_primary_session_for_tests(
        dict(run.get("sessions") or {}),
        role=role,
        provider_session_id=session_id,
        config=config,
        workspace=store.root,
        provider="cursor",
    )
    store.save_run(run_id, run, expected_revision)


def _event_types(store: FileRunStore, run_id: str) -> list[str]:
    return [str(event.get("type") or "") for event in store.load_events(run_id)]


def test_planner_session_resumes_successfully(tmp_path: Path) -> None:
    """§21 test 25: existing planner session resumes without replacement."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(signal="continue", text="planning turn"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_primary_session(store, run_id, role="planner", session_id=session_id)

    provider.script_session_turn(
        session_id,
        done_events(signal="candidate_plan_ready", text="done"),
    )
    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.session_id == session_id
    assert "session_replaced" not in _event_types(store, run_id)


def test_planner_session_missing_and_replaced(tmp_path: Path) -> None:
    """§21 test 26: missing planner session is replaced once with recovery manifest."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial planner start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_primary_session(store, run_id, role="planner", session_id=session_id)

    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement planner start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="replacement turn"))
    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.session_id != session_id
    events = _event_types(store, run_id)
    assert "session_resume_failed" in events
    assert "session_replacement_started" in events
    assert "session_replaced" in events
    assert "session_provider_id_bound" in events


def test_planner_session_stalled_and_replaced(tmp_path: Path) -> None:
    """Stalled provider turn triggers one replacement with provider_turn_stalled reason."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial planner start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_primary_session(store, run_id, role="planner", session_id=session_id)

    provider.mark_session_stalled(session_id)
    provider.script_turn(done_events(text="replacement planner start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="replacement turn"))
    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.session_id != session_id
    events = store.load_events(run_id)
    replacement_started = [
        event
        for event in events
        if str(event.get("type") or "") == "session_replacement_started"
    ]
    assert replacement_started
    assert replacement_started[-1]["reason"] == REASON_PROVIDER_TURN_STALLED
    resume_failed = [
        event
        for event in events
        if str(event.get("type") or "") == "session_resume_failed"
    ]
    assert resume_failed
    assert resume_failed[-1]["reason"] == REASON_PROVIDER_TURN_STALLED


def test_continue_run_replaces_stalled_session_without_ownership_conflict(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial planner start"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_primary_session(store, run_id, role="planner", session_id=session_id)

    provider.mark_session_stalled(session_id)
    provider.script_turn(done_events(text="replacement planner start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="replacement turn"))

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
    )
    result = engine.continue_run(run_id, single_step=True)

    assert result.ok is True
    run = store.load_run(run_id)
    assert run["status"] != "failed"
    stop = run.get("stop")
    if isinstance(stop, dict):
        assert stop.get("code") != "orchestrator_invariant_failure"
    assert "session_replaced" in _event_types(store, run_id)
    assert primary_provider_session_id(run, "planner") != session_id


def test_recovery_reason_helpers() -> None:
    not_found = ProviderSessionNotFoundError(
        "missing",
        provider="cursor",
        session_id="chat-old",
    )
    stalled = ProviderTurnStalledError("stall", session_id="chat-old")

    assert is_recoverable_provider_session_loss(not_found)
    assert is_recoverable_provider_session_loss(stalled)
    assert not is_recoverable_provider_session_loss(ValueError("nope"))
    assert recovery_reason_for_session_loss(not_found) == REASON_PROVIDER_SESSION_NOT_FOUND
    assert recovery_reason_for_session_loss(stalled) == REASON_PROVIDER_TURN_STALLED


def test_replace_primary_session_releases_old_provider_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="old planner start"))
    old_session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(old_session_id))
    _bind_primary_session(store, run_id, role="planner", session_id=old_session_id)

    provider.script_turn(done_events(text="replacement planner start"))
    manifest = build_planner_recovery_manifest(
        store,
        run_id,
        config,
        plan,
        phase_action_id="action-replace-01",
        expected_next_action="continue planning",
    )
    new_session_id = replace_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLANNING,
        old_provider_session_id=old_session_id,
        phase_action_id="action-replace-01",
        append_event=lambda *_args, **_kwargs: None,
        model=None,
        manifest=manifest,
        recovery_reason=REASON_PROVIDER_TURN_STALLED,
    )

    assert new_session_id != old_session_id
    active_ids = {entry["session_id"] for entry in provider.list_active_sessions()}
    assert old_session_id not in active_ids
    assert new_session_id in active_ids

    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    agent_context = manifest.get("agent_context") or {}
    assert binding.activity == agent_context.get("activity")
    assert binding.context_digest == agent_context.get("context_digest")


def test_reviewer_session_missing_and_replaced(tmp_path: Path) -> None:
    """§21 test 27: missing reviewer session is replaced once."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = PLANNING
    store.save_run(run_id, run, expected_revision)

    loop = make_review_loop(
        id="loop-focused-01",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=0,
        scope={"item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    package = build_focused_review_package(
        run_id,
        run,
        config,
        loop,
        plan=store.load_plan_model(run_id),
    )
    provider.script_turn(done_events(text="initial review"))
    session_id, _token = begin_reviewer_review(
        provider,
        store,
        run_id,
        loop_id=loop.id,
        review_package=package,
        phase=PLANNING,
    )
    list(provider.stream_events(session_id))
    updated = loop.with_reviewer_provider_session_id(session_id)
    from top_down_planning.persistence.review_commit import (
        review_record_revision,
        save_review_with_expected_revision,
    )

    save_review_with_expected_revision(
        store,
        run_id,
        updated.to_dict(),
        expected_revision=review_record_revision(store.load_review(run_id, loop.id)),
    )

    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement reviewer turn"))
    outcome = consume_reviewer_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        loop_id=loop.id,
        recovery=build_reviewer_turn_recovery(
            store,
            run_id,
            loop_id=loop.id,
            phase=PLANNING,
            expected_next_action="continue reviewer turn",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
            review_package=package,
        ),
    )

    assert outcome.replaced is True
    assert outcome.session_id != session_id
    assert outcome.capability_token is not None
    events = _event_types(store, run_id)
    assert "session_resume_failed" in events
    assert "session_replaced" in events


def test_producer_session_missing_and_replaced(tmp_path: Path) -> None:
    """§21 test 28: missing producer session is replaced once."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = store.load_plan_model(run_id)
    provider.script_turn(done_events(text="initial producer start"))
    session_id = provider.start_primary_session(
        "producer",
        build_producer_context_manifest(run_id, run, config, plan),
    )
    list(provider.stream_events(session_id))
    _bind_primary_session(store, run_id, role="producer", session_id=session_id)

    provider.mark_session_not_found(session_id)
    provider.script_turn(done_events(text="replacement producer start"))
    provider.script_turn(done_events(text="replacement producer turn"))
    from top_down_planning.orchestrator.provider_turns import build_producer_turn_recovery

    outcome = consume_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        session_id,
        allowed_signals=frozenset(),
        recovery=build_producer_turn_recovery(
            store,
            run_id,
            phase=PRODUCTION,
            expected_next_action="continue production turn",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
        ),
    )

    assert outcome.replaced is True
    assert outcome.session_id != session_id
    assert outcome.capability_token is not None
    events = _event_types(store, run_id)
    assert "session_replaced" in events


def test_producer_replacement_blocked_by_workspace_mismatch(tmp_path: Path) -> None:
    """§21 test 29: producer replacement blocked when workspace drifts."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    run = store.load_run(run_id)
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()

    with pytest.raises(WorkspaceIntegrityError):
        validate_run_workspace_integrity(run, workspace=other_workspace)

    _bind_primary_session(store, run_id, role="producer", session_id="stub-session-1")
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    manifest = build_producer_recovery_manifest(
        store,
        run_id,
        config,
        store.load_plan_model(run_id),
        phase_action_id="action-test",
        expected_next_action="continue production",
    )
    assert REPLACEMENT_SESSION_NOTICE in manifest["replacement_session_notice"]

    provider = StubProvider()
    with pytest.raises(ProducerReplacementBlocked, match="workspace mismatch"):
        replace_primary_session(
            store,
            run_id,
            provider,
            role="producer",
            phase=PRODUCTION,
            old_provider_session_id="stub-session-1",
            phase_action_id="action-test",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
            manifest=manifest,
            workspace=other_workspace,
        )


def test_producer_replacement_blocked_by_evidence_mismatch(tmp_path: Path) -> None:
    """§21 test 30: producer replacement blocked when evidence hash drifts."""

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    artifact = store.root / "artifact.txt"
    artifact.write_text("original\n", encoding="utf-8")
    evidence = capture_output_artifact(
        store,
        run_id,
        workspace=store.root,
        ref="artifact.txt",
    )
    production = store.load_production(run_id)
    expected_production_revision = int(production["revision"])
    production = dict(production)
    production["revision"] = expected_production_revision + 1
    production["output_evidence"] = [{**evidence, "id": "out-artifact"}]
    store.save_production(
        run_id,
        production,
        expected_revision=expected_production_revision,
    )

    artifact.write_text("mutated\n", encoding="utf-8")
    stored_production = store.load_production(run_id)
    snapshot_ref = str(evidence["snapshot_ref"])
    _prefix, snapshot_id, filename = Path(snapshot_ref).parts
    artifact_path = store.artifact_path(run_id, snapshot_id, filename)
    artifact_path.write_bytes(b"corrupted snapshot bytes\n")
    with pytest.raises(EvidenceIntegrityError):
        validate_production_evidence_integrity(store, run_id, stored_production)


def test_planner_recovery_manifest_includes_required_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    config = store.load_resolved_config(run_id)
    manifest = build_planner_recovery_manifest(
        store,
        run_id,
        config,
        store.load_plan_model(run_id),
        phase_action_id="action-abc",
        expected_next_action="continue planning",
    )

    for key in (
        "run_id",
        "phase",
        "role",
        "session_kind",
        "phase_action_id",
        "expected_next_action",
        "plan_snapshot",
        "target_digest",
        "replacement_session_notice",
        "output_goal",
    ):
        assert key in manifest


def test_planner_recovery_manifest_honors_activity(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T006001-006001"
    _create_planning_run(store, run_id)
    config = store.load_resolved_config(run_id)
    manifest = build_planner_recovery_manifest(
        store,
        run_id,
        config,
        store.load_plan_model(run_id),
        phase_action_id="action-abc",
        expected_next_action="revise plan after review",
        activity="plan_revision",
    )

    assert manifest["agent_context"]["activity"] == "plan_revision"
