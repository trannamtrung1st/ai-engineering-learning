"""Slice 5 rereview 568f97b: worker deadline, ITIMER-safe probes, replacement idempotency."""

from __future__ import annotations

import multiprocessing
import signal
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.session_lineage import (
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    StoreBoundaryProbe,
    _drain_provider_turn,
    _invoke_boundary_bounded,
    build_producer_turn_boundary_observer,
    owned_boundary_workers,
)
from top_down_planning.orchestrator.session_events import commit_primary_provider_session_binding
from top_down_planning.orchestrator.session_lineage import emit_session_replacement_failed
from top_down_planning.persistence import FileRunStore
from tests.unit.test_slice5_rereview_2af6712b_fixes import _lineage
from tests.unit.test_slice5_rereview_27eaa0b_fixes import SleepThenOk
from tests.unit.test_slice5_rereview_41a27ee_fixes import NeverReturnBoundary
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _RecordingDrainProvider,
    _create_run,
    _scripted,
)
from tests.unit.test_slice5_rereview_eb572b0_fixes import _unrecoverable_pending


def _alarm_guard():
    fired = {"n": 0}

    def _on_alrm(_signum, _frame) -> None:
        fired["n"] += 1

    previous = signal.signal(signal.SIGALRM, _on_alrm)
    return fired, previous


def test_standalone_invoke_includes_startup_in_timeout() -> None:
    started = time.monotonic()
    real_start = None

    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    real_start = BoundaryWorker.start

    def slow_start(self, *, deadline: float | None = None) -> None:
        time.sleep(0.25)
        return real_start(self, deadline=deadline)

    with patch.object(BoundaryWorker, "start", slow_start):
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _invoke_boundary_bounded(
                LiteralBoundarySignal(),
                threading.Event(),
                timeout=0.2,
            )
    assert time.monotonic() - started <= 0.45
    assert owned_boundary_workers() == ()


def test_drain_startup_failure_still_settles_provider_turn() -> None:
    provider = _RecordingDrainProvider(yield_event={"type": "assistant", "text": "x"})

    def boom(self, *, deadline: float | None = None, wait_ready: bool = True, **kwargs) -> None:
        del self, deadline, wait_ready, kwargs
        raise RuntimeError("worker start failed")

    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    with patch.object(BoundaryWorker, "start", boom):
        with pytest.raises(RuntimeError, match="worker start failed"):
            _drain_provider_turn(
                provider,
                "sess-start-fail",
                allowed_signals=frozenset(),
                on_boundary=LiteralBoundarySignal(),
            )
    assert provider.settled == ["sess-start-fail"]


def test_dead_boundary_worker_raises_typed_error() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    assert worker.proc is not None
    worker.proc.kill()
    worker.proc.wait(timeout=2.0)

    with pytest.raises(ProviderRunError, match="boundary worker died"):
        worker.invoke(LiteralBoundarySignal(), timeout=1.0)


def test_timeout_close_does_not_extend_deadline() -> None:
    started = time.monotonic()
    with pytest.raises(ProviderRunError, match="exceeded timeout"):
        _invoke_boundary_bounded(NeverReturnBoundary(), threading.Event(), timeout=0.2)
    assert time.monotonic() - started <= 0.55


def test_itimer_probe_does_not_kill_process_on_alarm() -> None:
    if not hasattr(signal, "setitimer"):
        pytest.skip("ITIMER_REAL is unavailable")
    fired, previous = _alarm_guard()
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.05)
        try:
            result = worker.invoke(SleepThenOk(), timeout=1.0)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, previous)
        worker.close()
    assert result == "ok"
    assert fired["n"] >= 1


def test_existing_failed_replacement_is_not_reclassified_as_legacy(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T090101-090101"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    binding = _unrecoverable_pending(store, run_id)
    emit_session_replacement_failed(
        store,
        run_id,
        phase="planning",
        role="planner",
        session_instance_id=binding.session_instance_id,
        generation=binding.generation,
        reason="replacement_identity",
        phase_action_id="action-identity",
    )
    before = store.load_run(run_id)
    assert before["status"] == "running"
    durable = "cursor-durable-already-failed"
    provider._ensure_durable_session(durable, role="planner", kind="primary")
    with pytest.raises(ProviderRunError, match="already failed"):
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
    assert failed[0]["reason"] == "replacement_identity"
    assert _lineage(store, run_id, SESSION_REPLACED) == []
    after = store.load_run(run_id)
    assert after["status"] == "running"
    assert after.get("stop") is None or after["stop"].get("code") != "session_recovery_exhausted"


def test_boundary_probe_rejects_non_file_run_store(tmp_path: Path) -> None:
    class _RootOnly:
        root = tmp_path

    with pytest.raises(ProviderRunError, match="FileRunStore"):
        build_producer_turn_boundary_observer(_RootOnly(), "run-x")  # type: ignore[arg-type]


def test_file_run_store_is_the_only_boundary_backend(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T090102-090102"
    _create_run(store, run_id)
    observer = build_producer_turn_boundary_observer(store, run_id)
    assert isinstance(observer, StoreBoundaryProbe)
    assert observer.store_root == str(store.root)
