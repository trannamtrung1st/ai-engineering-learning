"""Slice 5 rereview 065f8a22: allocation atomicity and drain quiescence."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.errors import ProviderSessionError
from top_down_planning.domain.session_lineage import (
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
)
from top_down_planning.orchestrator.errors import SessionRecoveryPaused
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_POLL_THREAD_NAME,
    PROVIDER_ABORT_THREAD_NAME,
    PROVIDER_EVENT_PUMP_NAME,
    _drain_provider_turn,
)
from top_down_planning.orchestrator.reviewer_session import begin_reviewer_review
from top_down_planning.orchestrator.session_context import (
    ensure_primary_session,
    rotate_primary_session,
)
from top_down_planning.orchestrator.session_events import (
    commit_primary_provider_session_binding,
    commit_reviewer_loop_provider_session,
)
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import make_review_loop
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _RecordingDrainProvider,
    _active_ids,
    _create_run,
    _lineage_types,
    _live_named,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


def test_fresh_planner_collision_does_not_emit_start_or_leave_unbound_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065001-065001"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id)
    provider.forced_primary_id = reviewer_id
    started: list[str] = []
    before = store.load_run(run_id)
    with pytest.raises(ProviderSessionError):
        ensure_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            requested=_requested("planner"),
            manifest={"goal": "x"},
            append_event=lambda event_type, **_k: started.append(str(event_type)),
            resume_request={"goal": "x"},
        )
    after = store.load_run(run_id)
    assert "planner_session_started" not in started
    assert store.list_capabilities(run_id) == []
    assert reviewer_id in _active_ids(provider)
    assert after["revision"] == before["revision"]
    binding = get_primary_binding(after, "planner")
    assert binding is None or binding.provider_session_id in {None, ""}


def test_rotation_validates_before_destroying_old_owner(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065002-065002"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id)
    before = store.load_run(run_id)
    before_gen = get_primary_binding(before, "planner").generation
    provider.forced_primary_id = reviewer_id
    started: list[str] = []
    with pytest.raises(ProviderSessionError):
        rotate_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=planner_id,
            requested=_requested("planner"),
            manifest={"goal": "x"},
            append_event=lambda event_type, **_k: started.append(str(event_type)),
        )
    after = store.load_run(run_id)
    assert planner_id in _active_ids(provider)
    assert reviewer_id in _active_ids(provider)
    assert "planner_session_started" not in started
    assert get_primary_binding(after, "planner").provider_session_id == planner_id
    assert get_primary_binding(after, "planner").generation == before_gen


def test_primary_replacement_collision_emits_failed_and_pauses(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065003-065003"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id)
    provider.forced_primary_id = reviewer_id
    with pytest.raises(SessionRecoveryPaused):
        replace_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=planner_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"goal": "x"},
        )
    types = _lineage_types(store, run_id)
    assert types.count(SESSION_REPLACEMENT_FAILED) == 1
    assert SESSION_REPLACED not in types
    assert planner_id in _active_ids(provider)
    assert reviewer_id in _active_ids(provider)
    run = store.load_run(run_id)
    assert run["status"] == "paused"


def test_reviewer_replacement_wrong_role_emits_failed_and_pauses(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065004-065004"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=reviewer_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    provider.forced_reviewer_id = planner_id
    with pytest.raises(SessionRecoveryPaused):
        replace_reviewer_session(
            store,
            run_id,
            provider,
            loop=loop,
            phase="whole_plan_review",
            old_provider_session_id=reviewer_id,
            phase_action_id="action-replace-01",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"loop_id": "review-whole-plan-01"},
        )
    types = _lineage_types(store, run_id)
    assert types.count(SESSION_REPLACEMENT_FAILED) == 1
    assert SESSION_REPLACED not in types
    assert planner_id in _active_ids(provider)
    assert reviewer_id in _active_ids(provider)
    assert store.load_run(run_id)["status"] == "paused"


def test_binding_requires_session_reference(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065005-065005"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    with pytest.raises(ProviderSessionError, match="not registered"):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id="cursor-durable-missing",
            provider="stub",
            session_provider=provider,
        )
    pending = "cursor-pending-missing"
    with pytest.raises(ProviderSessionError, match="not registered"):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id=pending,
            provider="stub",
            session_provider=provider,
        )
    provider._ensure_durable_session(pending, role="planner", kind="primary")
    committed = commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=pending,
        provider="stub",
        session_provider=provider,
    )
    starting = get_primary_binding(committed, "planner")
    assert starting is not None
    assert starting.provider_session_id == pending
    assert starting.state == "starting"

    durable = "cursor-durable-ok"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    committed = commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=durable,
        provider="stub",
        session_provider=provider,
    )
    bound = get_primary_binding(committed, "planner")
    assert bound is not None
    assert bound.provider_session_id == durable
    assert bound.state == "bound"

    wrong = "cursor-durable-reviewer"
    provider._ensure_durable_session(wrong, role="reviewer", kind="reviewer")
    with pytest.raises(ProviderSessionError, match="expected planner/primary"):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id=wrong,
            provider="stub",
            session_provider=provider,
        )


def test_commit_persists_canonical_durable_id_not_pending_alias(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065006-065006"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    pending = "cursor-pending-planner"
    durable = "cursor-durable-d"
    provider._ensure_durable_session(pending, role="planner", kind="primary")
    provider.aliases[pending] = durable
    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=pending,
        provider="stub",
        session_provider=provider,
    )
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id == durable
    assert binding.state == "bound"
    lineage = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "session_provider_id_bound"
    ]
    assert len(lineage) == 1
    assert lineage[0]["provider_session_id"] == durable


def test_reviewer_commit_rebuilds_binding_with_canonical_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065007-065007"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    pending = "cursor-pending-reviewer"
    durable = "cursor-durable-reviewer"
    provider._ensure_durable_session(pending, role="reviewer", kind="reviewer")
    provider.aliases[pending] = durable
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=pending)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=pending,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    committed = commit_reviewer_loop_provider_session(
        store,
        run_id,
        loop,
        session_provider=provider,
    )
    assert committed.reviewer_binding is not None
    assert committed.reviewer_binding.provider_session_id == durable
    assert committed.reviewer_binding.state == "bound"


def test_hanging_abort_leaves_zero_abort_workers() -> None:
    for _ in range(3):
        provider = _RecordingDrainProvider(hang_abort=True)
        with patch(
            "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
            0.1,
        ):
            started = time.monotonic()
            try:
                _drain_provider_turn(
                    provider,
                    "sess-1",
                    allowed_signals=frozenset(),
                    on_boundary=lambda: "paused",
                )
            except Exception:
                pass
            assert time.monotonic() - started < 2.0
        assert _live_named(PROVIDER_ABORT_THREAD_NAME) == []
        provider.released.set()


def test_blocked_boundary_callback_leaves_zero_poll_workers() -> None:
    blocked = threading.Event()

    def on_boundary() -> str | None:
        blocked.wait(timeout=0.01)
        return "paused"

    provider = _RecordingDrainProvider()
    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.1,
    ), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.1,
    ):
        started = time.monotonic()
        _drain_provider_turn(
            provider,
            "sess-1",
            allowed_signals=frozenset(),
            on_boundary=on_boundary,
        )
        assert time.monotonic() - started < 2.0
    assert _live_named(BOUNDARY_POLL_THREAD_NAME) == []
    provider.released.set()


def test_hanging_terminate_is_bounded_and_pump_quiesces() -> None:
    provider = _RecordingDrainProvider(hang_terminate=True, unblock_on_abort=True)
    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.1,
    ), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.1,
    ):
        started = time.monotonic()
        try:
            _drain_provider_turn(
                provider,
                "sess-1",
                allowed_signals=frozenset(),
                on_boundary=lambda: "paused",
            )
        except Exception:
            pass
        assert time.monotonic() - started < 2.0
    assert _live_named(PROVIDER_EVENT_PUMP_NAME) == []
    provider.released.set()


def test_stream_ignores_terminate_but_abort_still_quiesces_pump() -> None:
    provider = _RecordingDrainProvider(
        unblock_on_terminate=False,
        unblock_on_abort=True,
    )
    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.1,
    ):
        started = time.monotonic()
        _drain_provider_turn(
            provider,
            "sess-1",
            allowed_signals=frozenset(),
            on_boundary=lambda: "paused",
        )
        assert time.monotonic() - started < 2.0
    assert _live_named(PROVIDER_EVENT_PUMP_NAME) == []
    provider.released.set()


def test_poll_error_and_pump_survivor_diagnostics_are_preserved() -> None:
    provider = _RecordingDrainProvider(
        abort_error=RuntimeError("abort failed"),
        hang_abort=True,
    )

    def on_boundary() -> str | None:
        raise RuntimeError("poll boom")

    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.1,
    ), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.1,
    ):
        started = time.monotonic()
        with pytest.raises(RuntimeError) as caught:
            _drain_provider_turn(
                provider,
                "sess-1",
                allowed_signals=frozenset(),
                on_boundary=on_boundary,
            )
        assert time.monotonic() - started < 2.0
    combined = f"{caught.value} {getattr(caught.value, '__notes__', [])}"
    assert "poll boom" in combined or "abort failed" in combined
    assert _live_named(PROVIDER_EVENT_PUMP_NAME) == []
    provider.released.set()


def test_begin_reviewer_does_not_bind_capability_on_collision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T065008-065008"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    provider.forced_reviewer_id = planner_id
    with pytest.raises(ProviderSessionError):
        begin_reviewer_review(
            provider,
            store,
            run_id,
            loop_id="review-whole-plan-01",
            review_package={"loop_id": "review-whole-plan-01"},
            phase="whole_plan_review",
        )
    reviewer_caps = [
        cap
        for cap in store.list_capabilities(run_id)
        if cap.get("role") == "reviewer"
    ]
    assert reviewer_caps == []
    assert planner_id in _active_ids(provider)
