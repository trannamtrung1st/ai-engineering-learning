"""Slice 5 rereview b8a5a80: killable late Popen, unreaped sweep, POSIX policy."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderUnsupportedPlatformError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    _invoke_boundary_bounded,
    reap_unreaped_boundary_workers,
    unreaped_boundary_workers,
)


def test_late_returning_popen_is_reaped_after_deadline() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker
    import sys

    def hang_ready(*args, **kwargs):
        del args
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            pass_fds=kwargs.get("pass_fds", ()),
            close_fds=kwargs.get("close_fds", True),
            start_new_session=True,
        )

    worker = BoundaryWorker()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(hang_ready)):
            started = time.monotonic()
            with pytest.raises(ProviderRunError, match="exceeded timeout"):
                worker.start(deadline=time.monotonic() + 0.05)
            assert time.monotonic() - started < 0.25
        worker.close(cleanup_timeout=1.0)
        assert worker.proc is None
        assert worker not in unreaped_boundary_workers()
    finally:
        worker.close(cleanup_timeout=1.0)
        reap_unreaped_boundary_workers(timeout=1.0)


def test_blocked_popen_does_not_use_startup_helper_thread() -> None:
    import sys

    def hang_ready(*args, **kwargs):
        del args
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            pass_fds=kwargs.get("pass_fds", ()),
            close_fds=kwargs.get("close_fds", True),
            start_new_session=True,
        )

    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(hang_ready)):
            started = time.monotonic()
            with pytest.raises(ProviderRunError, match="exceeded timeout"):
                worker.start(deadline=time.monotonic() + 0.05)
            assert time.monotonic() - started < 0.25
        assert [
            item.name
            for item in threading.enumerate()
            if item.name in {"tdp-boundary-start", "tdp-boundary-popen"}
        ] == []
    finally:
        worker.close(cleanup_timeout=0.2)
        try:
            reap_unreaped_boundary_workers(timeout=0.2)
        except ProviderRunError:
            pass


def test_sweep_reaps_worker_that_survived_first_close() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    assert worker.proc is not None
    with patch.object(type(worker.proc), "poll", return_value=None), patch.object(
        type(worker.proc), "wait", return_value=None
    ), patch.object(type(worker.proc), "kill", return_value=None):
        with pytest.raises(ProviderRunError, match="failed to stop"):
            worker.close(cleanup_timeout=0.0)
        assert unreaped_boundary_workers()
    reap_unreaped_boundary_workers(timeout=1.0)
    assert worker not in unreaped_boundary_workers()
    assert worker.proc is None


def test_oneshot_failed_close_stays_owned_until_teardown() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    def fail_close(self, **kwargs) -> None:
        del kwargs
        raise ProviderRunError("boundary worker failed to stop")

    try:
        with patch.object(BoundaryWorker, "close", fail_close):
            with pytest.raises(ProviderRunError, match="failed to stop"):
                _invoke_boundary_bounded(
                    LiteralBoundarySignal(),
                    threading.Event(),
                    timeout=1.0,
                )
        assert unreaped_boundary_workers()
        owned = unreaped_boundary_workers()[0]
        teardown_provider_sessions(
            StubProvider(),
            run_id="run-boundary-sweep",
            phase=PLANNING,
            append_event=lambda *_args, **_kwargs: None,
            emit_console=lambda _event: None,
        )
        assert owned not in unreaped_boundary_workers()
        assert owned.proc is None
    finally:
        for leftover in unreaped_boundary_workers():
            BoundaryWorker.close(leftover)


def test_windows_stub_boundary_polling_is_typed_posix_only() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    with patch("top_down_planning.orchestrator.provider_turns.sys.platform", "win32"):
        with pytest.raises(ProviderUnsupportedPlatformError, match="POSIX"):
            worker.start()
    assert worker.proc is None

