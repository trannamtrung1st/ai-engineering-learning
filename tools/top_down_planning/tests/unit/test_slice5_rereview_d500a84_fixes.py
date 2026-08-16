"""Slice 5 rereview d500a84: OK token and identity-safe spawn cleanup."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.provider_turns import BoundaryWorker


class _FakeHelper:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.killed = False
        self.waited = False

    def poll(self):
        return None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        return -1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_garbage_ready_token_is_worker_death() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    reaped: list[object] = []

    def fake_spawn(*_args, **_kwargs):
        return helper

    def fake_reap(proc, *, timeout):
        reaped.append(proc)

    with patch(
        "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
        fake_spawn,
    ), patch.object(worker, "_reap_local_proc", fake_reap), patch(
        "select.select", return_value=([3], [], [])
    ), patch("os.read", return_value=b"NOPE"), patch(
        "os.close"
    ), patch("os.set_inheritable"), patch("os.pipe", return_value=(3, 4)):
        result = worker._popen_via_constructor_helper(
            7, env={}, deadline=time.monotonic() + 1
        )
    assert result is None
    assert "boundary worker died" in str(worker._launch_error)
    assert reaped == [helper]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_eof_ready_token_is_worker_death() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    reaped: list[object] = []

    def fake_reap(proc, *, timeout):
        reaped.append(proc)

    with patch(
        "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
        lambda *_a, **_k: helper,
    ), patch.object(worker, "_reap_local_proc", fake_reap), patch(
        "select.select", return_value=([3], [], [])
    ), patch("os.read", return_value=b""), patch("os.close"), patch(
        "os.set_inheritable"
    ), patch("os.pipe", return_value=(3, 4)):
        result = worker._popen_via_constructor_helper(
            7, env={}, deadline=time.monotonic() + 1
        )
    assert result is None
    assert "boundary worker died" in str(worker._launch_error)
    assert reaped == [helper]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_ok_ready_token_returns_helper() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    with patch(
        "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
        lambda *_a, **_k: helper,
    ), patch("select.select", return_value=([3], [], [])), patch(
        "os.read", return_value=b"OK\n"
    ), patch("os.close"), patch("os.set_inheritable"), patch(
        "os.pipe", return_value=(3, 4)
    ):
        assert worker._popen_via_constructor_helper(7, env={}, deadline=None) is helper


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_okgarbage_ready_token_is_worker_death() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    reaped: list[object] = []
    with patch(
        "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
        lambda *_a, **_k: helper,
    ), patch.object(worker, "_reap_local_proc", lambda proc, *, timeout: reaped.append(proc)), patch(
        "select.select", return_value=([3], [], [])
    ), patch("os.read", return_value=b"OKgarbage"), patch("os.close"), patch(
        "os.set_inheritable"
    ), patch("os.pipe", return_value=(3, 4)):
        result = worker._popen_via_constructor_helper(7, env={}, deadline=time.monotonic() + 1)
    assert result is None
    assert reaped == [helper]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_reap_does_not_killpg_on_identity_mismatch() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    from core_tools.provider.process_identity import (
        IdentityInspectState,
        ProcessIdentity,
    )

    setattr(
        helper,
        "_tdp_spawn_identity",
        ProcessIdentity(pid=4242, start_time="100"),
    )
    signaled: list[tuple[int, int]] = []
    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.IDENTITY_MISMATCH,
    ), patch("os.killpg", side_effect=lambda pgid, sig: signaled.append((pgid, sig))):
        worker._reap_local_proc(helper, timeout=0.05)
    assert signaled == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_reap_does_not_killpg_when_identity_unverifiable() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    from core_tools.provider.process_identity import (
        IdentityInspectState,
        ProcessIdentity,
    )

    setattr(
        helper,
        "_tdp_spawn_identity",
        ProcessIdentity(pid=4242, start_time="100"),
    )
    signaled: list[tuple[int, int]] = []
    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ), patch("os.killpg", side_effect=lambda pgid, sig: signaled.append((pgid, sig))):
        worker._reap_local_proc(helper, timeout=0.05)
    assert signaled == []
    assert helper.killed is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_identity_is_attached_before_ready_wait() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper(pid=os.getpid())
    order: list[str] = []

    def fake_spawn(*_args, **_kwargs):
        order.append("spawn")
        return helper

    def fake_identity(pid, timeout=None):
        order.append("identity")
        from core_tools.provider.process_identity import ProcessIdentity

        return ProcessIdentity(pid=pid, start_time="1")

    def fake_select(*_args, **_kwargs):
        order.append("select")
        return ([3], [], [])

    with patch(
        "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
        fake_spawn,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        fake_identity,
    ), patch("select.select", fake_select), patch("os.read", return_value=b"OK"), patch(
        "os.close"
    ), patch("os.set_inheritable"), patch("os.pipe", return_value=(3, 4)):
        worker._popen_via_constructor_helper(7, env={}, deadline=None)
    assert order[:3] == ["spawn", "identity", "select"]
    assert getattr(helper, "_tdp_spawn_identity") is not None
