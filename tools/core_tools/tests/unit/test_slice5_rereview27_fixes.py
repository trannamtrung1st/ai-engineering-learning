"""Slice 5 twenty-seventh re-review regressions (S5-RR27-001 through S5-RR27-005)."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    wait_process_group_gone,
)
from core_tools.provider.process_identity import (
    TerminateIdentityResult,
    _fallback_kill_bound_janitor_group,
    _terminate_bound_process,
    _terminate_via_bound_popen,
)
from core_tools.provider.session_janitor import (
    DrainResult,
    JanitorOwnerState,
    JanitorStatusOwner,
)


def _pipe() -> tuple[int, int]:
    return os.pipe()


def _status_payload(drain: DrainResult) -> bytes:
    return (
        json.dumps(
            {
                "agent_code": 1,
                "drain": drain.value,
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
    def __init__(self, pid: int = 4242) -> None:
        self.stdin = _Stdin()
        self.pid = pid
        self.reaped = False
        self.wait_calls = 0
        self.alive = True

    def poll(self) -> int | None:
        if self.alive:
            self.reaped = True
            self.alive = False
        return 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.reaped = True
        self.alive = False
        return 0


class _LiveProc(_FakeProc):
    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        raise subprocess.TimeoutExpired(cmd="janitor", timeout=timeout)


def _bind(proc: _FakeProc, payload: bytes | None = None) -> JanitorStatusOwner:
    status_r, status_w = _pipe()
    if payload is not None:
        os.write(status_w, payload)
        os.close(status_w)
    else:
        proc._status_w = status_w  # type: ignore[attr-defined]
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    return owner


@pytest.mark.parametrize("drain", [DrainResult.SURVIVORS, DrainResult.UNVERIFIABLE])
def test_nonclean_terminal_status_does_not_allow_reap(drain: DrainResult) -> None:
    proc = _FakeProc()
    owner = _bind(proc, _status_payload(drain))
    status = owner.read(timeout=1.0)
    assert status is not None
    assert status["drain"] == drain.value
    assert owner.reap_allowed is False
    assert proc.poll() is None
    assert proc.reaped is False
    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(timeout=0.05)
    assert proc.wait_calls == 0


def test_clean_terminal_status_still_allows_reap() -> None:
    proc = _FakeProc()
    owner = _bind(
        proc,
        json.dumps(
            {
                "agent_code": 0,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": True,
            }
        ).encode("utf-8")
        + b"\n",
    )
    assert owner.read(timeout=1.0)["drain"] == DrainResult.CLEAN.value
    assert owner.reap_allowed is True
    assert proc.poll() == 0
    assert proc.reaped is True


def test_killpg_eperm_never_reports_clean() -> None:
    proc = _LiveProc()
    err = OSError(errno.EPERM, "denied")
    err.errno = errno.EPERM
    with patch(
        "core_tools.provider.process_identity.os.killpg",
        side_effect=err,
    ):
        with patch(
            "core_tools.provider.process_identity.list_process_group_pids",
            return_value=[proc.pid],
        ):
            payload = _fallback_kill_bound_janitor_group(proc, pgid=proc.pid)
    assert payload["drain"] != DrainResult.CLEAN.value
    assert payload["drain"] == DrainResult.UNVERIFIABLE.value


def test_killpg_oserror_never_reports_clean() -> None:
    proc = _LiveProc()
    with patch(
        "core_tools.provider.process_identity.os.killpg",
        side_effect=OSError("boom"),
    ):
        with patch(
            "core_tools.provider.process_identity.list_process_group_pids",
            return_value=[proc.pid],
        ):
            payload = _fallback_kill_bound_janitor_group(proc, pgid=proc.pid)
    assert payload["drain"] != DrainResult.CLEAN.value


def test_killpg_esrch_with_empty_group_is_clean() -> None:
    proc = _FakeProc()
    err = OSError(errno.ESRCH, "gone")
    err.errno = errno.ESRCH
    with patch(
        "core_tools.provider.process_identity.os.killpg",
        side_effect=err,
    ):
        with patch(
            "core_tools.provider.process_identity.list_process_group_pids",
            return_value=[],
        ):
            with patch(
                "core_tools.provider.process_identity.is_pid_alive",
                return_value=False,
            ):
                payload = _fallback_kill_bound_janitor_group(
                    proc, pgid=proc.pid, output_handed_off=True
                )
    assert payload["drain"] == DrainResult.CLEAN.value


def test_successful_killpg_with_live_leader_is_not_terminated() -> None:
    proc = _LiveProc()
    owner = _bind(proc)
    os.close(proc._status_w)  # type: ignore[attr-defined]
    with patch(
        "core_tools.provider.process_identity.JANITOR_PARENT_WAIT_SECONDS",
        0.08,
    ):
        with patch(
            "core_tools.provider.process_identity.os.killpg",
            return_value=None,
        ):
            with patch(
                "core_tools.provider.process_identity.wait_process_group_gone",
                return_value=ProcessGroupState.GONE,
            ):
                with patch(
                    "core_tools.provider.process_identity.list_process_group_pids",
                    return_value=[proc.pid],
                ):
                    with patch(
                        "core_tools.provider.process_identity.is_pid_alive",
                        return_value=True,
                    ):
                        with patch(
                            "core_tools.provider.process_identity.drain_owned_process_group",
                            return_value=False,
                        ):
                            result = _terminate_bound_process(None, proc, pgid=proc.pid)
    assert result is not TerminateIdentityResult.TERMINATED
    assert owner.reap_allowed is False
    status = proc._core_tools_janitor_status
    assert status["drain"] != DrainResult.CLEAN.value


def test_fallback_survivors_and_unverifiable_forbid_reap() -> None:
    for drain in (DrainResult.SURVIVORS, DrainResult.UNVERIFIABLE):
        proc = _FakeProc()
        owner = _bind(proc)
        os.close(proc._status_w)  # type: ignore[attr-defined]
        payload = {
            "agent_code": -1,
            "drain": drain.value,
            "stop_requested": True,
        }
        with patch(
            "core_tools.provider.process_identity.JANITOR_PARENT_WAIT_SECONDS",
            0.05,
        ):
            with patch(
                "core_tools.provider.process_identity._fallback_kill_bound_janitor_group",
                return_value=payload,
            ):
                returned = _terminate_via_bound_popen(proc, pgid=proc.pid)
        assert returned == payload
        assert owner.reap_allowed is False
        assert proc.poll() is None
        assert proc.reaped is False
        owner.mark_safe_fallback(
            {
                "agent_code": 0,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": True,
            }
        )
        assert owner.reap_allowed is True
        proc.wait(timeout=0.05)
        assert proc.wait_calls == 1


def test_darwin_ps_stall_returns_unverifiable_within_deadline() -> None:
    proc = _LiveProc()
    seen: dict[str, float | None] = {}

    def listing(pgid: int, *, timeout: float | None = None) -> list[int] | None:
        seen["timeout"] = timeout
        return None

    started = time.monotonic()
    with patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        side_effect=listing,
    ):
        with patch(
            "core_tools.provider.process_identity.os.killpg",
            return_value=None,
        ):
            with patch(
                "core_tools.provider.process_identity.wait_process_group_gone",
                return_value=ProcessGroupState.UNVERIFIABLE,
            ):
                payload = _fallback_kill_bound_janitor_group(
                    proc,
                    pgid=proc.pid,
                    timeout=0.15,
                )
    elapsed = time.monotonic() - started
    assert elapsed < 0.45
    assert seen["timeout"] is not None
    assert seen["timeout"] <= 0.15
    assert payload["drain"] == DrainResult.UNVERIFIABLE.value


def test_darwin_ps_honors_subprocess_timeout() -> None:
    from core_tools.provider.process_cleanup import _list_darwin_process_group_pids

    def stall(*args: object, **kwargs: object) -> object:
        timeout = kwargs.get("timeout")
        assert timeout == 0.12
        raise subprocess.TimeoutExpired(cmd="ps", timeout=float(timeout))

    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        side_effect=stall,
    ):
        assert _list_darwin_process_group_pids(1, timeout=0.12) is None


def test_wait_process_group_gone_counts_scan_time() -> None:
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    def slow_state(pgid: int, *, timeout: float | None = None) -> ProcessGroupState:
        clock["now"] += 0.4
        return ProcessGroupState.LIVE

    with patch("core_tools.provider.process_cleanup.time.monotonic", monotonic):
        with patch(
            "core_tools.provider.process_cleanup.process_group_state",
            side_effect=slow_state,
        ):
            with patch("core_tools.provider.process_cleanup.time.sleep", lambda _s: None):
                state = wait_process_group_gone(7, timeout=0.5)
    assert state is ProcessGroupState.LIVE
    assert clock["now"] >= 0.5


def test_stale_reader_timeout_does_not_downgrade_safe_fallback() -> None:
    proc = _FakeProc()
    owner = _bind(proc)
    started = threading.Event()
    finished = threading.Event()

    def reader() -> None:
        started.set()
        owner.read(timeout=0.4)
        finished.set()

    thread = threading.Thread(target=reader)
    thread.start()
    started.wait(timeout=1.0)
    time.sleep(0.03)
    owner.mark_safe_fallback(
        {
            "agent_code": 0,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        }
    )
    assert owner.reap_allowed is True
    proc.wait(timeout=0.2)
    assert proc.wait_calls == 1
    finished.wait(timeout=1.0)
    thread.join(timeout=1.0)
    assert owner.reap_allowed is True
    assert owner._state is JanitorOwnerState.SAFE_FALLBACK_COMPLETE
    os.close(proc._status_w)  # type: ignore[attr-defined]
    owner.close()
    owner.close()
    second = _terminate_via_bound_popen(proc, pgid=proc.pid)
    assert isinstance(second, dict)
    assert second.get("drain") == DrainResult.CLEAN.value
