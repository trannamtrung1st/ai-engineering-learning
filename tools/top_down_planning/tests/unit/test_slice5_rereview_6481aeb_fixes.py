"""Slice 5 rereview 6481aeb: boundary bound, lineage atomicity, identity cleanup."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.errors import ProviderReplacementIdentityError
from top_down_planning.domain.session_lineage import (
    SESSION_PROVIDER_ID_BOUND,
    SESSION_REPLACED,
    SESSION_REPLACEMENT_STARTED,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryExhausted
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_turns import (
    PROVIDER_EVENT_PUMP_NAME,
    _drain_provider_turn,
    _invoke_boundary_bounded,
    build_planner_turn_recovery,
    consume_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.orchestrator.session_events import (
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import done_events, make_review_loop
from tests.unit.test_slice5_rereview_27eaa0b_fixes import _PendingSameIdOnStreamStub
from tests.unit.test_slice5_rereview_2af6712b_fixes import _helper_threads, _lineage
from tests.unit.test_slice5_rereview_c947561_fixes import _PendingSameIdStub
from tests.unit.test_slice5_rereview_2af6712b_fixes import _helper_threads, _lineage
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _active_ids,
    _create_run,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


def _idle_or_pump_survivors() -> list[threading.Thread]:
    names = {PROVIDER_EVENT_PUMP_NAME, "cursor-idle-stream"}
    return [
        thread
        for thread in threading.enumerate()
        if thread.name in names and thread.is_alive()
    ]


def test_never_returning_boundary_callback_fails_within_timeout() -> None:
    side_effects: list[str] = []

    def callback() -> str | None:
        threading.Event().wait()
        side_effects.append("ran")
        return "paused"

    started = time.monotonic()
    with patch("ctypes.pythonapi.PyThreadState_SetAsyncExc") as async_exc:
        with pytest.raises(ProviderRunError, match="boundary probe exceeded timeout"):
            _invoke_boundary_bounded(callback, threading.Event(), timeout=0.15)
    assert time.monotonic() - started <= 0.5
    assert async_exc.call_count == 0
    assert side_effects == []
    assert _helper_threads() == []


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


def test_primary_pending_replacement_emits_true_old_and_new_instance_ids(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050101-050101"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdStub())
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
    old_instance = get_primary_binding(store.load_run(run_id), "planner").session_instance_id
    pending = _replace_primary(store, run_id, provider, old_id, "action-replace-a1")
    new_instance = get_primary_binding(store.load_run(run_id), "planner").session_instance_id
    assert old_instance != new_instance
    started = _lineage(store, run_id, SESSION_REPLACEMENT_STARTED)[-1]
    assert started["old_session_instance_id"] == old_instance
    assert started["new_session_instance_id"] == new_instance
    durable = "cursor-durable-primary-a1"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    provider.aliases[pending] = durable
    sync_persisted_session_id(provider, store, run_id, pending, role="planner")
    replaced = _lineage(store, run_id, SESSION_REPLACED)
    assert len(replaced) == 1
    assert replaced[0]["old_session_instance_id"] == old_instance
    assert replaced[0]["new_session_instance_id"] == new_instance
    assert replaced[0]["new_provider_session_id"] == durable


def test_reviewer_pending_replacement_emits_true_old_and_new_instance_ids(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050102-050102"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdStub())
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
    review = store.load_review(run_id, "review-whole-plan-01")
    old_instance = (review.get("reviewer_binding") or {}).get("session_instance_id")
    pending = replace_reviewer_session(
        store,
        run_id,
        provider,
        loop=loop,
        phase="whole_plan_review",
        old_provider_session_id=old_id,
        phase_action_id="action-replace-r-a1",
        append_event=lambda *_a, **_k: None,
        model="test-model",
        manifest={"loop_id": "review-whole-plan-01"},
    )
    after = store.load_review(run_id, "review-whole-plan-01")
    new_instance = (after.get("reviewer_binding") or {}).get("session_instance_id")
    assert old_instance and new_instance and old_instance != new_instance
    durable = "cursor-durable-reviewer-a1"
    provider._ensure_durable_session(durable, role="reviewer", kind="reviewer")
    provider.aliases[pending] = durable
    sync_reviewer_loop_session_id(
        provider, store, run_id, "review-whole-plan-01", pending
    )
    replaced = _lineage(store, run_id, SESSION_REPLACED)
    assert len(replaced) == 1
    assert replaced[0]["old_session_instance_id"] == old_instance
    assert replaced[0]["new_session_instance_id"] == new_instance


def test_durable_promotion_rolls_back_when_replaced_event_staging_fails(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050201-050201"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdStub())
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
    pending = _replace_primary(store, run_id, provider, old_id, "action-replace-a2")
    durable = "cursor-durable-primary-a2"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    provider.aliases[pending] = durable
    original = store.commit

    def boom(target_run_id: str, spec: CommitSpec):
        types = [event.get("type") for event in spec.events or []]
        if SESSION_REPLACED in types:
            raise PersistenceError("replaced staging failed")
        return original(target_run_id, spec)

    with patch.object(store, "commit", side_effect=boom):
        with pytest.raises(PersistenceError, match="replaced staging failed"):
            sync_persisted_session_id(provider, store, run_id, pending, role="planner")
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id != durable
    assert _lineage(store, run_id, SESSION_REPLACED) == []
    sync_persisted_session_id(provider, store, run_id, pending, role="planner")
    replaced = _lineage(store, run_id, SESSION_REPLACED)
    bound = _lineage(store, run_id, SESSION_PROVIDER_ID_BOUND)
    assert len(replaced) == 1
    assert bound
    assert replaced[0]["new_provider_session_id"] == durable


def test_capability_rebind_failure_after_atomic_success_retries(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050202-050202"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdStub())
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
    pending = _replace_primary(store, run_id, provider, old_id, "action-replace-a3")
    durable = "cursor-durable-primary-a3"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    provider.aliases[pending] = durable
    with patch(
        "top_down_planning.orchestrator.session_events.rebind_primary_session_capability",
        side_effect=PersistenceError("capability rebind failed"),
    ):
        with pytest.raises(PersistenceError, match="capability rebind failed"):
            sync_persisted_session_id(provider, store, run_id, pending, role="planner")
    assert len(_lineage(store, run_id, SESSION_REPLACED)) == 1
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id == durable
    sync_persisted_session_id(provider, store, run_id, pending, role="planner")
    assert len(_lineage(store, run_id, SESSION_REPLACED)) == 1


class _IdentityConflictTerminateBoom(_PendingSameIdOnStreamStub):
    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        canonical = self.canonical_session_id(session_id)
        if session_id == self.pending_id or canonical == self.pending_id:
            raise RuntimeError("terminate boom")
        return super().terminate_session(session_id, timeout=timeout)


def test_identity_conflict_preserves_cause_when_terminate_raises(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050301-050301"
    _create_run(store, run_id)
    provider = _scripted(_IdentityConflictTerminateBoom())
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
    with pytest.raises(SessionRecoveryExhausted) as caught:
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
    assert isinstance(caught.value.__cause__, ProviderReplacementIdentityError)
    notes = getattr(caught.value, "__notes__", [])
    assert any("terminate boom" in note or "still active" in note for note in notes)


class _IdentityConflictStillActive(_PendingSameIdOnStreamStub):
    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        canonical = self.canonical_session_id(session_id)
        if session_id == self.pending_id or canonical == self.pending_id:
            return
        return super().terminate_session(session_id, timeout=timeout)


def test_identity_conflict_surfaces_still_active_cleanup(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050302-050302"
    _create_run(store, run_id)
    provider = _scripted(_IdentityConflictStillActive())
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
    with pytest.raises(SessionRecoveryExhausted) as caught:
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
    assert isinstance(caught.value.__cause__, ProviderReplacementIdentityError)
    notes = getattr(caught.value, "__notes__", [])
    assert any("still active" in note for note in notes)


@pytest.mark.skipif(sys.platform == "win32", reason="select on pipes")
def test_cursor_drain_abort_leaves_no_event_pump(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    first = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'
    script = f"print({first!r}, flush=True)\nimport time\ntime.sleep(60)\n"

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.0,
                    "max_retries_per_call": 0,
                }
            }
        },
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.4,
    ), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.4,
    ):
        result = _drain_provider_turn(
            provider,
            session_id,
            allowed_signals=frozenset(),
            on_boundary=lambda: "paused",
        )
    assert result == "paused"
    assert _idle_or_pump_survivors() == []
    assert _helper_threads() == []
