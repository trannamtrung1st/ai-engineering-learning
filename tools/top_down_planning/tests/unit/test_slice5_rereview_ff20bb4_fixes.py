"""Slice 5 rereview ff20bb4: wrapped stores, full probe budget, typed worker death."""

from __future__ import annotations

import multiprocessing
import signal
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.notifications.options import NotificationOptions
from top_down_planning.notifications.store import NotificationContext, wrap_run_store
from top_down_planning.observability import ObservabilityContext, wrap_store_with_observability
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    StoreBoundaryProbe,
    _invoke_boundary_bounded,
    build_producer_turn_boundary_observer,
    build_reviewer_decision_boundary_observer,
)
from top_down_planning.persistence import FileRunStore
from tests.unit.test_slice5_rereview_ee5de8e_fixes import _create_run, _save_reviewer_loop


class _SleepAlmostTimeout:
    def __call__(self) -> str | None:
        time.sleep(0.18)
        return "ok"


def test_observing_wrapper_builds_producer_and_reviewer_probes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T100101-100101"
    _create_run(store, run_id)
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id="cursor-r-1")
    wrapped = wrap_store_with_observability(store, ObservabilityContext())
    producer = build_producer_turn_boundary_observer(wrapped, run_id)
    reviewer = build_reviewer_decision_boundary_observer(
        wrapped, run_id, "review-whole-plan-01"
    )
    assert isinstance(producer, StoreBoundaryProbe)
    assert isinstance(reviewer, StoreBoundaryProbe)
    assert producer.store_root == str(store.root)
    assert reviewer.store_root == str(store.root)


def test_notifying_observing_wrapper_builds_producer_probe(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T100102-100102"
    _create_run(store, run_id)
    wrapped = wrap_run_store(
        store,
        observability=ObservabilityContext(),
        notifications=NotificationContext(options=NotificationOptions()),
    )
    observer = build_producer_turn_boundary_observer(wrapped, run_id)
    assert isinstance(observer, StoreBoundaryProbe)
    assert observer.store_root == str(store.root)


def test_prestarted_worker_uses_full_response_poll_budget() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    try:
        parent = worker.parent_conn
        assert parent is not None
        seen: list[float] = []
        real_poll = parent.poll

        def tracking_poll(timeout: float | None = None) -> bool:
            if timeout is not None:
                seen.append(float(timeout))
            return real_poll(timeout)

        parent.poll = tracking_poll  # type: ignore[method-assign]
        result = worker.invoke(LiteralBoundarySignal(), timeout=0.4)
    finally:
        worker.close()
    assert result is None
    assert seen
    assert seen[0] >= 0.37


def test_blocked_process_start_times_out_without_inline_wait() -> None:
    hang_bootstrap = "import time; time.sleep(60)\n"
    started = time.monotonic()
    with patch(
        "top_down_planning.orchestrator.provider_turns._WORKER_BOOTSTRAP",
        hang_bootstrap,
    ):
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _invoke_boundary_bounded(
                LiteralBoundarySignal(),
                threading.Event(),
                timeout=0.2,
            )
    assert time.monotonic() - started <= 0.55
    assert [
        proc
        for proc in multiprocessing.active_children()
        if "tdp-boundary" in (proc.name or "")
    ] == []


def test_ipc_death_after_send_is_typed_worker_died() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    assert worker.parent_conn is not None
    real_send = worker.parent_conn.send

    def dying_send(payload) -> None:
        del payload
        assert worker.proc is not None
        worker.proc.kill()
        worker.proc.wait(timeout=2.0)
        raise BrokenPipeError("child gone")

    worker.parent_conn.send = dying_send  # type: ignore[method-assign]
    try:
        with pytest.raises(ProviderRunError, match="boundary worker died"):
            worker.invoke(LiteralBoundarySignal(), timeout=1.0)
    finally:
        parent = worker.parent_conn
        if parent is not None:
            parent.send = real_send  # type: ignore[method-assign]
        worker.close()


def test_unreaped_worker_keeps_handle_and_raises() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    assert worker.proc is not None
    with patch.object(type(worker.proc), "poll", return_value=None), patch.object(
        type(worker.proc), "wait", return_value=None
    ), patch.object(type(worker.proc), "kill", return_value=None):
        with pytest.raises(ProviderRunError, match="failed to stop"):
            worker.close(cleanup_timeout=0.0)
        assert worker.proc is not None
    worker.close()


def test_itimer_handler_records_alarm_delivery() -> None:
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
        signal.setitimer(signal.ITIMER_REAL, 0.05)
        try:
            result = worker.invoke(_SleepAlmostTimeout(), timeout=1.0)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, previous)
        worker.close()
    assert result == "ok"
    assert fired["n"] >= 1
