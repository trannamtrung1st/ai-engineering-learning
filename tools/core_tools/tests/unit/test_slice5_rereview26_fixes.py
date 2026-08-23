"""Slice 5 twenty-sixth re-review regressions (S5-RR26-001 through S5-RR26-003)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import is_pid_alive, terminate_process_tree
from core_tools.provider.process_identity import (
    TerminateIdentityResult,
    _terminate_bound_process,
    _terminate_via_bound_popen,
)
from core_tools.provider.session_janitor import (
    DrainResult,
    JanitorStatusOwner,
    read_bound_janitor_status,
)


def _pipe() -> tuple[int, int]:
    return os.pipe()


def _clean_payload() -> bytes:
    return (
        json.dumps(
            {
                "agent_code": 0,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": True,
            }
        ).encode("utf-8")
        + b"\n"
    )


class _Stdin:
    def write(self, data: object) -> int:
        return len(data) if isinstance(data, (bytes, str)) else 0

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeProc:
    def __init__(self) -> None:
        self.stdin = _Stdin()
        self.pid = 4242
        self.reaped = False
        self.killed = False
        self.wait_calls = 0
        self.wait_timeouts: list[float | None] = []

    def poll(self) -> int | None:
        self.reaped = True
        return 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        self.reaped = True
        return 0

    def kill(self) -> None:
        self.killed = True


def _wait_pid_file(path: Path, timeout: float = 2.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.02)
    raise AssertionError(f"pid file was not written: {path}")


def test_status_timeout_does_not_publish_or_close_channel() -> None:
    status_r, status_w = _pipe()
    proc = _FakeProc()
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner

    assert owner.read(timeout=0.08) is None
    assert proc.poll() is None
    assert proc.reaped is False
    assert owner.reap_allowed is False

    os.write(status_w, _clean_payload())
    os.close(status_w)
    status = owner.read(timeout=1.0)
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert proc.poll() == 0


def test_concurrent_wait_does_not_reap_while_status_read_pending() -> None:
    status_r, status_w = _pipe()
    proc = _FakeProc()
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    started = threading.Event()
    waiter_done = threading.Event()
    wait_error: list[BaseException] = []

    def reader() -> None:
        started.set()
        owner.read(timeout=1.0)

    def waiter() -> None:
        started.wait(timeout=1.0)
        time.sleep(0.02)
        try:
            proc.wait(timeout=0.15)
        except subprocess.TimeoutExpired:
            pass
        except BaseException as exc:  # pragma: no cover
            wait_error.append(exc)
        waiter_done.set()

    reader_thread = threading.Thread(target=reader)
    waiter_thread = threading.Thread(target=waiter)
    reader_thread.start()
    waiter_thread.start()
    waiter_done.wait(timeout=1.0)
    assert waiter_done.is_set()
    assert wait_error == []
    assert proc.reaped is False
    assert proc.wait_calls == 0
    os.write(status_w, _clean_payload())
    os.close(status_w)
    reader_thread.join(timeout=1.0)
    assert owner.read(timeout=0.2)["drain"] == DrainResult.CLEAN.value
    proc.wait(timeout=0.2)
    assert proc.wait_calls == 1


def _controlled_monotonic(
    monkeypatch: pytest.MonkeyPatch, *, start: float = 1000.0
) -> dict[str, float]:
    clock = {"now": start}

    def fake_monotonic() -> float:
        return clock["now"]

    monkeypatch.setattr("core_tools.provider.session_janitor.time.monotonic", fake_monotonic)
    return clock


def test_wait_deducts_status_read_from_one_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 0.2s wait budget must shrink by status-read time before raw_wait."""

    clock = _controlled_monotonic(monkeypatch)
    status_r, status_w = _pipe()
    proc = _FakeProc()
    owner = JanitorStatusOwner(status_r)
    read_timeouts: list[float] = []

    def consume_then_clean(*, timeout: float) -> dict[str, object]:
        read_timeouts.append(timeout)
        clock["now"] += 0.15
        status = {
            "agent_code": 0,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        }
        owner.mark_safe_fallback(status)
        return status

    owner.read = consume_then_clean  # type: ignore[method-assign]
    owner.bind(proc)
    try:
        assert proc.wait(timeout=0.2) == 0
        assert read_timeouts == [pytest.approx(0.2)]
        assert proc.wait_calls == 1
        assert proc.wait_timeouts == [pytest.approx(0.05)]
        assert proc.wait_timeouts[0] != 0.2
    finally:
        os.close(status_w)
        os.close(status_r)


def test_wait_timeout_does_not_call_raw_wait_when_status_never_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If status never becomes CLEAN, wait times out and must not reap via raw_wait."""

    clock = _controlled_monotonic(monkeypatch)
    status_r, status_w = _pipe()
    proc = _FakeProc()
    owner = JanitorStatusOwner(status_r)
    read_timeouts: list[float] = []

    def consume_budget(*, timeout: float) -> None:
        read_timeouts.append(timeout)
        clock["now"] += max(0.0, timeout)
        return None

    owner.read = consume_budget  # type: ignore[method-assign]
    owner.bind(proc)
    try:
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            proc.wait(timeout=0.2)
        assert exc_info.value.timeout == 0.2
        assert read_timeouts == [pytest.approx(0.2)]
        assert proc.wait_calls == 0
        assert proc.wait_timeouts == []
        assert proc.reaped is False
    finally:
        os.close(status_w)
        os.close(status_r)


def test_close_does_not_release_poll_barrier_while_reader_inflight() -> None:
    status_r, status_w = _pipe()
    proc = _FakeProc()
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    started = threading.Event()
    result: list[dict[str, object] | None] = []

    def reader() -> None:
        started.set()
        result.append(owner.read(timeout=1.0))

    thread = threading.Thread(target=reader)
    thread.start()
    started.wait(timeout=1.0)
    time.sleep(0.03)
    owner.close()
    owner.close()
    assert proc.poll() is None
    assert proc.reaped is False
    assert owner.reap_allowed is False
    os.write(status_w, _clean_payload())
    os.close(status_w)
    thread.join(timeout=1.0)
    assert thread.is_alive() is False
    assert result == [
        {
            "agent_code": 0,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        }
    ]


def test_close_without_status_does_not_allow_reap() -> None:
    status_r, status_w = _pipe()
    proc = _FakeProc()
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    owner.close()
    owner.close()
    os.close(status_w)
    assert proc.poll() is None
    assert proc.reaped is False
    assert owner.reap_allowed is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_missing_status_kills_group_before_reaping_leader(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, time\n"
        f"path = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "open(path, 'w', encoding='utf-8').write(str(child))\n"
        "time.sleep(60)\n"
    )
    status_r, status_w = os.pipe()
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(status_w,),
    )
    os.close(status_w)
    child_pid = _wait_pid_file(child_pid_file)
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    kill_while_unresolved: list[str] = []
    raw_kill = proc.kill

    def tracking_kill() -> None:
        if is_pid_alive(child_pid):
            kill_while_unresolved.append("leader")
        raw_kill()

    proc.kill = tracking_kill  # type: ignore[method-assign]
    try:
        with patch(
            "core_tools.provider.process_identity.JANITOR_PARENT_WAIT_SECONDS",
            0.12,
        ):
            result = _terminate_bound_process(None, proc, pgid=proc.pid)
        assert kill_while_unresolved == []
        assert is_pid_alive(child_pid) is False
        assert is_pid_alive(proc.pid) is False
        status = getattr(proc, "_core_tools_janitor_status", None)
        assert isinstance(status, dict)
        assert status["drain"] in {
            DrainResult.CLEAN.value,
            DrainResult.SURVIVORS.value,
            DrainResult.UNVERIFIABLE.value,
        }
        assert result in {
            TerminateIdentityResult.TERMINATED,
            TerminateIdentityResult.FAILED,
        }
        second = terminate_process_tree(proc, pgid=proc.pid)
        assert second is True
    finally:
        if is_pid_alive(child_pid):
            os.kill(child_pid, 9)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, 9)
            except OSError:
                proc.kill()
            raw_wait = getattr(proc, "_core_tools_raw_wait", proc.wait)
            raw_wait(timeout=2)
