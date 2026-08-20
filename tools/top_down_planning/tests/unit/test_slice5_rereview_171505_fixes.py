"""Slice 5 rereview 171505: killable constructors, identity-safe survivors, sweep notes."""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

import pytest

from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_teardown import _session_surviving_pids
from top_down_planning.orchestrator.provider_turns import (
    owned_boundary_workers,
    reap_unreaped_boundary_workers,
    unreaped_boundary_workers,
)


def _popen_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "tdp-boundary-popen" and thread.is_alive()
    ]


def _fd_count() -> int:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    return 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_repeated_blocked_constructors_do_not_grow_host_owners() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    hang_helper = "import threading; threading.Event().wait()\n"
    baseline_threads = len(_popen_threads())
    baseline_fds = _fd_count()
    with patch(
        "top_down_planning.orchestrator.provider_turns._CONSTRUCTOR_HELPER",
        hang_helper,
    ):
        for _ in range(20):
            worker = BoundaryWorker()
            worker.start(deadline=time.monotonic() + 0.08, wait_ready=False)
            try:
                worker.close(cleanup_timeout=0.15)
            except ProviderRunError:
                pass
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline and len(_popen_threads()) > baseline_threads:
                time.sleep(0.02)
            assert len(_popen_threads()) <= baseline_threads
            assert owned_boundary_workers() == ()
            assert unreaped_boundary_workers() == ()
            assert _fd_count() <= baseline_fds + 4
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline and len(_popen_threads()) > baseline_threads:
        time.sleep(0.02)
    assert len(_popen_threads()) <= baseline_threads
    assert owned_boundary_workers() == ()
    assert unreaped_boundary_workers() == ()


def test_session_surviving_pids_count_zombie_not_reused_mismatch() -> None:
    session = {"session_id": "cursor-session-1", "role": "planner"}
    records = [
        {
            "pid": 4242,
            "session_id": "cursor-session-1",
            "start_time": "100",
            "process_identity": "4242:100",
            "member_identities": ["4242:100", "5151:200"],
            "reason": "termination_failed",
        }
    ]

    class _Provider:
        def canonical_session_id(self, session_id: str) -> str:
            return session_id

    def fake_inspect(identity: ProcessIdentity, timeout=None):
        del timeout
        if identity.pid == 4242:
            return IdentityInspectState.ZOMBIE
        return IdentityInspectState.IDENTITY_MISMATCH

    with patch(
        "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
        side_effect=fake_inspect,
    ), patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        survivors = _session_surviving_pids(
            session,
            provider=_Provider(),  # type: ignore[arg-type]
            termination_records=records,
        )
    assert survivors == [4242]


def test_sweep_aggregates_close_diagnostics_into_final_error() -> None:
    from top_down_planning.orchestrator import provider_turns as turns

    class _Stubborn:
        def close(self, *, cleanup_timeout: float | None = None) -> None:
            del cleanup_timeout
            raise OSError("fd still held")

    with turns._BOUNDARY_WORKER_LOCK:
        turns._UNREAPED_BOUNDARY_WORKERS[id(_Stubborn)] = _Stubborn()  # type: ignore[assignment]
    try:
        with pytest.raises(ProviderRunError, match="boundary worker failed to stop") as caught:
            reap_unreaped_boundary_workers(timeout=0.05)
        notes = getattr(caught.value, "__notes__", [])
        assert any("fd still held" in str(note) for note in notes)
    finally:
        with turns._BOUNDARY_WORKER_LOCK:
            turns._UNREAPED_BOUNDARY_WORKERS.pop(id(_Stubborn), None)
            for key, worker in list(turns._UNREAPED_BOUNDARY_WORKERS.items()):
                if type(worker).__name__ == "_Stubborn":
                    turns._UNREAPED_BOUNDARY_WORKERS.pop(key, None)
