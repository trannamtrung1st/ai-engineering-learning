"""Slice 5 twenty-eighth re-review regressions (S5-RR28-001 through S5-RR28-004)."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    _list_darwin_process_group_pids,
    inspect_pid_liveness,
    list_process_group_pids,
)
from core_tools.provider.process_identity import (
    TerminateIdentityResult,
    _fallback_kill_bound_janitor_group,
    _terminate_bound_process,
)
from core_tools.provider.session_janitor import (
    DrainResult,
    JanitorStatusOwner,
)


def _pipe() -> tuple[int, int]:
    return os.pipe()


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
        self.wait_timeouts: list[float | None] = []

    def poll(self) -> int | None:
        self.reaped = True
        return 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        self.reaped = True
        return 0


class _HungWaitProc(_FakeProc):
    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        if timeout is None:
            time.sleep(5)
        raise subprocess.TimeoutExpired(cmd="janitor", timeout=timeout)


def _bind(proc: _FakeProc, payload: bytes | None = None) -> JanitorStatusOwner:
    status_r, status_w = _pipe()
    if payload is not None:
        os.write(status_w, payload)
        os.close(status_w)
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    return owner


def test_darwin_group_scan_classifies_state_without_nested_liveness() -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        assert kwargs.get("timeout") == 0.2
        return SimpleNamespace(returncode=0, stdout="10 99 S\n11 99 Z\n12 98 S\n")

    hung = {"count": 0}

    def hang_liveness(pid: int, *, timeout: float | None = None) -> object:
        hung["count"] += 1
        time.sleep(2)
        raise AssertionError("nested liveness should not run")

    with patch("core_tools.provider.process_cleanup.subprocess.run", side_effect=fake_run):
        with patch(
            "core_tools.provider.process_cleanup.inspect_pid_liveness",
            side_effect=hang_liveness,
        ):
            started = time.monotonic()
            members = _list_darwin_process_group_pids(99, timeout=0.2)
            elapsed = time.monotonic() - started
    assert elapsed < 0.5
    assert hung["count"] == 0
    assert members == [10, 11]
    assert any("state=" in " ".join(argv) for argv in calls)


def test_esrch_leader_liveness_honors_timeout() -> None:
    proc = _HungWaitProc()
    seen: dict[str, float | None] = {}

    def alive(pid: int, *, timeout: float | None = None) -> bool:
        seen["timeout"] = timeout
        if timeout is None:
            time.sleep(2)
        return True

    err = OSError(errno.ESRCH, "gone")
    err.errno = errno.ESRCH
    started = time.monotonic()
    with patch("core_tools.provider.process_identity.os.killpg", side_effect=err):
        with patch(
            "core_tools.provider.process_identity.list_process_group_pids",
            return_value=[],
        ):
            with patch(
                "core_tools.provider.process_identity.is_pid_alive",
                side_effect=alive,
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


def test_wait_none_after_clean_is_still_bounded() -> None:
    payload = (
        json.dumps(
            {
                "agent_code": 0,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": True,
            }
        ).encode("utf-8")
        + b"\n"
    )
    proc = _HungWaitProc()
    owner = _bind(proc, payload)
    started = time.monotonic()
    with patch(
        "core_tools.provider.session_janitor.JANITOR_PARENT_WAIT_SECONDS",
        0.2,
    ):
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait()
    elapsed = time.monotonic() - started
    assert elapsed < 0.6
    assert proc.wait_timeouts
    assert proc.wait_timeouts[0] is not None
    assert owner.reap_allowed is True


def test_wait_explicit_timeout_still_uses_one_budget() -> None:
    proc = _HungWaitProc()
    owner = _bind(proc)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(timeout=0.2)
    elapsed = time.monotonic() - started
    os.close(owner._fd) if owner._fd is not None else None
    assert elapsed < 0.4
    assert proc.wait_calls == 0


def test_secondary_drain_finalizes_owner_and_reaps() -> None:
    proc = _FakeProc()
    owner = _bind(proc)
    with patch(
        "core_tools.provider.process_identity.JANITOR_PARENT_WAIT_SECONDS",
        0.05,
    ):
        with patch(
            "core_tools.provider.process_identity._fallback_kill_bound_janitor_group",
            return_value={
                "agent_code": -1,
                "drain": DrainResult.UNVERIFIABLE.value,
                "stop_requested": True,
            },
        ):
            with patch(
                "core_tools.provider.process_identity.drain_owned_process_group",
                return_value=True,
            ):
                result = _terminate_bound_process(None, proc, pgid=proc.pid)
    assert result is TerminateIdentityResult.FAILED
    assert owner.reap_allowed is False
    assert owner._fd is None
    assert owner._status is not None
    assert owner._status["drain"] != DrainResult.CLEAN.value


def test_linux_proc_scan_honors_timeout() -> None:
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    def listdir(_path: str) -> list[str]:
        return ["100", "101", "102"]

    def slow_stat(pid: int) -> object:
        clock["now"] += 0.2
        from core_tools.provider.process_cleanup import (
            LinuxProcStat,
            PidInspectResult,
            PidInspectState,
        )

        return PidInspectResult(
            PidInspectState.LIVE,
            LinuxProcStat(pid=pid, state="S", pgid=7, start_time="1"),
        )

    with patch("core_tools.provider.process_cleanup.sys.platform", "linux"):
        with patch("core_tools.provider.process_cleanup._linux_proc_available", return_value=True):
            with patch("core_tools.provider.process_cleanup.time.monotonic", monotonic):
                with patch("core_tools.provider.process_cleanup.os.listdir", listdir):
                    with patch(
                        "core_tools.provider.process_cleanup._read_linux_proc_stat",
                        side_effect=slow_stat,
                    ):
                        members = list_process_group_pids(7, timeout=0.25)
    assert members is None
