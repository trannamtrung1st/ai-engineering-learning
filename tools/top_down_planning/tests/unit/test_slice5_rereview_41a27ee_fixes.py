"""Slice 5 rereview 41a27ee: spawn-bounded probes, unique replacement terminals."""

from __future__ import annotations

import os
import threading
import time
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.persistence import PersistenceError
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.domain.session_lineage import (
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryExhausted
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_POLL_THREAD_NAME,
    PROVIDER_EVENT_PUMP_NAME,
    _drain_provider_turn,
    _invoke_boundary_bounded,
    build_planner_turn_recovery,
    consume_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.domain.session_bindings import PRIMARY_PLANNER_SLOT, SessionBinding
from top_down_planning.orchestrator.session_events import (
    _pending_replacement_success_payload,
    discard_unbound_provider_session,
)
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.orchestrator.session_recovery_enforcement import (
    fail_session_recovery_exhausted,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.session_bindings import (
    bump_primary_binding_generation,
    get_primary_binding,
    update_primary_binding,
)
from tests.helpers import done_events, make_review_loop
from tests.unit.test_slice5_rereview_27eaa0b_fixes import _PendingSameIdOnStreamStub
from tests.unit.test_slice5_rereview_2af6712b_fixes import _helper_threads, _lineage
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _RecordingDrainProvider,
    _create_run,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


class NeverReturnBoundary:
    def __call__(self) -> str | None:
        threading.Event().wait()
        return "paused"


def _replace_primary(store, run_id, provider, old_id: str, action: str) -> str:
    return replace_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        old_provider_session_id=old_id,
        phase_action_id=action,
        append_event=lambda *_a, **_k: None,
        model="test-model",
        manifest={"goal": "x"},
    )


def test_stalled_drain_never_return_boundary_leaves_no_helpers() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with patch(
            "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
            0.4,
        ), patch(
            "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
            0.4,
        ), patch("os.fork", side_effect=AssertionError("raw fork")):
            with pytest.raises(ProviderRunError, match="boundary probe exceeded timeout"):
                _drain_provider_turn(
                    _RecordingDrainProvider(),
                    "sess-stall",
                    allowed_signals=frozenset(),
                    on_boundary=NeverReturnBoundary(),
                )
    names = {thread.name for thread in threading.enumerate() if thread.is_alive()}
    assert BOUNDARY_POLL_THREAD_NAME not in names
    assert PROVIDER_EVENT_PUMP_NAME not in names
    assert _helper_threads() == []


def test_never_return_boundary_is_bounded_without_fork() -> None:
    with patch.object(os, "fork", side_effect=AssertionError("raw fork"), create=True):
        started = time.monotonic()
        with pytest.raises(ProviderRunError, match="boundary probe exceeded timeout"):
            _invoke_boundary_bounded(NeverReturnBoundary(), threading.Event(), timeout=0.4)
        assert time.monotonic() - started <= 1.5
    assert _helper_threads() == []


def test_immediate_durable_primary_replacement_emits_one_success(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060101-060101"
    _create_run(store, run_id)
    provider = _scripted(StubProvider())
    old_id = ensure_primary_session(
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
    _replace_primary(store, run_id, provider, old_id, "action-imm-p")
    generation = get_primary_binding(store.load_run(run_id), "planner").generation
    started = [
        event
        for event in _lineage(store, run_id, SESSION_REPLACEMENT_STARTED)
        if event.get("generation") == generation
    ]
    replaced = [
        event
        for event in _lineage(store, run_id, SESSION_REPLACED)
        if event.get("generation") == generation
    ]
    assert len(started) == 1
    assert len(replaced) == 1
    assert _lineage(store, run_id, SESSION_REPLACEMENT_FAILED) == []


def test_immediate_durable_reviewer_replacement_emits_one_success(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060102-060102"
    _create_run(store, run_id)
    provider = _scripted(StubProvider())
    old_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=old_id)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=old_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    replace_reviewer_session(
        store,
        run_id,
        provider,
        loop=loop,
        phase="whole_plan_review",
        old_provider_session_id=old_id,
        phase_action_id="action-imm-r",
        append_event=lambda *_a, **_k: None,
        model="test-model",
        manifest={"loop_id": "review-whole-plan-01"},
    )
    after = store.load_review(run_id, "review-whole-plan-01")
    generation = (after.get("reviewer_binding") or {}).get("generation")
    replaced = [
        event
        for event in _lineage(store, run_id, SESSION_REPLACED)
        if event.get("generation") == generation
    ]
    assert len(replaced) == 1
    assert _lineage(store, run_id, SESSION_REPLACEMENT_FAILED) == []


def test_injected_post_success_emit_cannot_add_failure(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060103-060103"
    _create_run(store, run_id)
    provider = _scripted(StubProvider())
    old_id = ensure_primary_session(
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
    with patch(
        "top_down_planning.orchestrator.session_lineage.emit_session_replaced",
        side_effect=PersistenceError("legacy success append"),
    ):
        _replace_primary(store, run_id, provider, old_id, "action-imm-fail")
    generation = get_primary_binding(store.load_run(run_id), "planner").generation
    replaced = [
        event
        for event in _lineage(store, run_id, SESSION_REPLACED)
        if event.get("generation") == generation
    ]
    failed = [
        event
        for event in _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
        if event.get("generation") == generation
    ]
    assert len(replaced) == 1
    assert failed == []


class _AliasNoopTerminate:
    def canonical_session_id(self, session_id: str) -> str:
        return "D" if session_id in {"P", "D"} else session_id

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        del session_id, timeout

    def list_active_sessions(self):
        return [{"session_id": "D"}]


def test_identity_conflict_canonical_alias_fails_closed() -> None:
    with pytest.raises(ProviderSessionError, match="still active"):
        discard_unbound_provider_session(
            _AliasNoopTerminate(),
            "P",
            preexisting_ids={"D"},
            timeout=0.1,
        )


def test_old_format_pending_promotion_does_not_emit_self_edge(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060104-060104"
    _create_run(store, run_id)
    provider = _scripted(StubProvider())
    ensure_primary_session(
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
    run = store.load_run(run_id)
    old_binding = get_primary_binding(run, "planner")
    assert old_binding is not None
    expected = int(run["revision"])
    sessions = bump_primary_binding_generation(run["sessions"], role="planner")
    pending_id = "cursor-pending-old-format"
    sessions = update_primary_binding(
        sessions,
        role="planner",
        provider_session_id=pending_id,
        provider="stub",
    )
    new_binding = SessionBinding.from_dict(sessions[PRIMARY_PLANNER_SLOT])
    updated = dict(run)
    updated["revision"] = expected + 1
    updated["sessions"] = sessions
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected,
            events=[
                {
                    "type": SESSION_REPLACEMENT_STARTED,
                    "run_id": run_id,
                    "phase": "planning",
                    "role": "planner",
                    "session_instance_id": new_binding.session_instance_id,
                    "generation": new_binding.generation,
                    "reason": "provider_turn_stalled",
                }
            ],
        ),
    )
    payload = _pending_replacement_success_payload(
        store,
        run_id,
        role="planner",
        generation=new_binding.generation,
        provider_session_id="cursor-durable-old-format",
        new_session_instance_id=new_binding.session_instance_id,
    )
    assert payload is not None
    assert payload["old_session_instance_id"] == old_binding.session_instance_id
    assert payload["new_session_instance_id"] == new_binding.session_instance_id
    assert payload["old_session_instance_id"] != payload["new_session_instance_id"]


def test_recovery_exhaustion_revokes_replacement_capability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T060105-060105"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdOnStreamStub())
    old_id = ensure_primary_session(
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
    provider.mark_session_stalled(old_id)
    provider.script_turn(done_events(text="replacement turn"))
    with pytest.raises(SessionRecoveryExhausted):
        consume_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            old_id,
            allowed_signals=frozenset(),
            recovery=build_planner_turn_recovery(
                store,
                run_id,
                phase=PLANNING,
                expected_next_action="continue planning",
                append_event=lambda *_a, **_k: None,
                model="test-model",
            ),
        )
    caps = store.list_capabilities(run_id)
    assert caps
    assert all(record.get("revoked") is True for record in caps)
    token_path = store.active_capability_token_path(run_id)
    assert not token_path.exists()
    with pytest.raises(SessionRecoveryExhausted):
        fail_session_recovery_exhausted(
            store,
            run_id,
            phase="planning",
            role="planner",
            phase_action_id="retry-revoke",
            message="retry",
        )
    assert all(record.get("revoked") is True for record in store.list_capabilities(run_id))
    assert not store.active_capability_token_path(run_id).exists()
