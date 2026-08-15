"""Slice 5 rereview eb572b0: one boundary worker per turn, terminalized legacy replacement."""

from __future__ import annotations

import multiprocessing
import os
import signal
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.session_lineage import (
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryExhausted
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    _drain_provider_turn,
    _invoke_boundary_bounded,
    build_producer_turn_boundary_observer,
)
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.session_events import (
    commit_primary_provider_session_binding,
    commit_reviewer_loop_provider_session,
)
from top_down_planning.domain.session_bindings import PRIMARY_PLANNER_SLOT, SessionBinding
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.session_bindings import (
    bump_primary_binding_generation,
    get_primary_binding,
    update_primary_binding,
)
from tests.helpers import save_review_payload
from tests.unit.test_slice5_rereview_2af6712b_fixes import _helper_threads, _lineage
from tests.unit.test_slice5_rereview_41a27ee_fixes import NeverReturnBoundary
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _RecordingDrainProvider,
    _create_run,
    _requested,
    _save_reviewer_loop,
    _scripted,
)
from tests.unit.test_slice5_rereview_27eaa0b_fixes import SleepThenOk
from top_down_planning.orchestrator.session_context import ensure_primary_session


class _ManyEventProvider:
    def stream_events(self, session_id: str):
        del session_id
        for index in range(120):
            yield {"type": "assistant", "text": str(index)}

    def abort_turn(self, session_id: str, *, timeout: float = 2.0) -> None:
        del session_id, timeout

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        del session_id, timeout

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        del session_id, timeout

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


def test_drain_starts_one_boundary_worker_for_many_events() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    starts = {"n": 0}
    real_start = BoundaryWorker.start

    def counting_start(self, *, deadline: float | None = None) -> None:
        starts["n"] += 1
        return real_start(self, deadline=deadline)

    with patch.object(BoundaryWorker, "start", counting_start):
        result = _drain_provider_turn(
            _ManyEventProvider(),
            "sess-many",
            allowed_signals=frozenset(),
            on_boundary=LiteralBoundarySignal(),
        )
    assert result is None
    assert starts["n"] == 1
    assert _helper_threads() == []


def test_silent_provider_does_not_respawn_boundary_worker() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    starts = {"n": 0}
    real_start = BoundaryWorker.start

    def counting_start(self, *, deadline: float | None = None) -> None:
        starts["n"] += 1
        return real_start(self, deadline=deadline)

    provider = _RecordingDrainProvider()
    with patch.object(BoundaryWorker, "start", counting_start), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.4,
    ):
        started = time.monotonic()
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _drain_provider_turn(
                provider,
                "sess-silent",
                allowed_signals=frozenset(),
                on_boundary=NeverReturnBoundary(),
            )
        assert time.monotonic() - started <= 2.0
    provider.released.set()
    assert starts["n"] == 1
    assert _helper_threads() == []


def test_blocked_boundary_worker_is_reaped_before_return() -> None:
    started = time.monotonic()
    with pytest.raises(ProviderRunError, match="exceeded timeout"):
        _invoke_boundary_bounded(NeverReturnBoundary(), threading.Event(), timeout=0.4)
    assert time.monotonic() - started <= 1.5
    assert [
        proc
        for proc in multiprocessing.active_children()
        if "tdp-boundary" in (proc.name or "")
    ] == []


def test_boundary_invoke_does_not_crash_preexisting_itimer() -> None:
    if not hasattr(signal, "setitimer"):
        pytest.skip("ITIMER_REAL is unavailable")
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    fired = {"n": 0}

    def _on_alrm(_signum, _frame) -> None:
        fired["n"] += 1

    previous = signal.signal(signal.SIGALRM, _on_alrm)
    worker = BoundaryWorker()
    worker.start()
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.5)
        try:
            result = worker.invoke(SleepThenOk(), timeout=1.0)
            remaining, _interval = signal.getitimer(signal.ITIMER_REAL)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, previous)
        worker.close()
    assert result == "ok"
    assert remaining == 0 or remaining < 0.45


def _unrecoverable_pending(store, run_id: str) -> SessionBinding:
    ensure_primary_session(
        store,
        run_id,
        _scripted(_ForcedIdStub()),
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    run = store.load_run(run_id)
    expected = int(run["revision"])
    sessions = bump_primary_binding_generation(run["sessions"], role="planner")
    pending_id = "cursor-pending-unrecoverable"
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
    events_path = store.run_dir(run_id) / "events.jsonl"
    kept = [
        line
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if "run_created" in line or SESSION_REPLACEMENT_STARTED in line
    ]
    events_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return new_binding


def test_unrecoverable_legacy_replacement_emits_failed_and_revokes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T080101-080101"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    _unrecoverable_pending(store, run_id)
    durable = "cursor-durable-unrecoverable"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    with pytest.raises(SessionRecoveryExhausted):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id=durable,
            provider="stub",
            session_provider=provider,
        )
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(failed) == 1
    assert failed[0]["reason"] == "legacy_identity_unrecoverable"
    assert _lineage(store, run_id, SESSION_REPLACED) == []
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "session_recovery_exhausted"
    caps = store.list_capabilities(run_id)
    assert all(record.get("revoked") is True for record in caps)
    assert not store.active_capability_token_path(run_id).exists()
    with pytest.raises(SessionRecoveryExhausted):
        commit_primary_provider_session_binding(
            store,
            run_id,
            role="planner",
            provider_session_id=durable,
            provider="stub",
            session_provider=provider,
        )
    assert len(_lineage(store, run_id, SESSION_REPLACEMENT_FAILED)) == 1


def test_unrecoverable_legacy_reviewer_replacement_emits_failed_and_revokes(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T080103-080103"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
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
    old_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=old_id)
    loop = ReviewLoop.from_dict(store.load_review(run_id, "review-whole-plan-01"))
    assert loop.reviewer_binding is not None
    pending_id = "cursor-pending-reviewer-unrecoverable"
    binding = loop.reviewer_binding.with_next_generation().with_provider_session_id(
        pending_id,
        provider="stub",
    )
    loop = replace(loop, reviewer_binding=binding)
    save_review_payload(store, run_id, loop.to_dict())
    run = store.load_run(run_id)
    expected = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected + 1
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected,
            events=[
                {
                    "type": SESSION_REPLACEMENT_STARTED,
                    "run_id": run_id,
                    "phase": "whole_plan_review",
                    "role": "reviewer",
                    "session_instance_id": binding.session_instance_id,
                    "generation": binding.generation,
                    "loop_id": loop.id,
                    "reason": "provider_turn_stalled",
                }
            ],
        ),
    )
    events_path = store.run_dir(run_id) / "events.jsonl"
    kept = [
        line
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if "run_created" in line or SESSION_REPLACEMENT_STARTED in line
    ]
    events_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    durable = "cursor-durable-reviewer-unrecoverable"
    provider._ensure_durable_session(durable, role="reviewer", kind="reviewer")
    pending_loop = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    pending_loop = pending_loop.with_reviewer_provider_session_id(
        durable,
        provider="stub",
    )
    with pytest.raises(SessionRecoveryExhausted):
        commit_reviewer_loop_provider_session(
            store,
            run_id,
            pending_loop,
            session_provider=provider,
        )
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(failed) == 1
    assert failed[0]["reason"] == "legacy_identity_unrecoverable"
    assert failed[0]["role"] == "reviewer"
    assert _lineage(store, run_id, SESSION_REPLACED) == []
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "session_recovery_exhausted"
    caps = store.list_capabilities(run_id)
    assert all(record.get("revoked") is True for record in caps)
    assert not store.active_capability_token_path(run_id).exists()
    with pytest.raises(SessionRecoveryExhausted):
        commit_reviewer_loop_provider_session(
            store,
            run_id,
            pending_loop,
            session_provider=provider,
        )
    assert len(_lineage(store, run_id, SESSION_REPLACEMENT_FAILED)) == 1


def test_file_store_root_is_the_documented_boundary_backend(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T080102-080102"
    _create_run(store, run_id)
    observer = build_producer_turn_boundary_observer(store, run_id)
    assert observer.store_root == str(store.root)
    assert observer() is None
