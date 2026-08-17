"""Slice 5 twenty-ninth re-review regressions (S5-RR29-001 through S5-RR29-003)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    inspect_pid_liveness,
    is_pid_alive,
    list_process_group_pids,
    terminate_process_tree,
    wait_process_group_gone,
)
from core_tools.provider.process_identity import (
    TerminateIdentityResult,
    _terminate_bound_process,
)
from core_tools.provider.session_janitor import DrainResult, JanitorStatusOwner
from tests.conftest import tracked_turn_proc


def _pipe() -> tuple[int, int]:
    return os.pipe()


def _fd_closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


def _fd_count() -> int:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    raise AssertionError("cannot count process file descriptors")


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

    def poll(self) -> int | None:
        self.reaped = True
        return 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.reaped = True
        return 0


def _bind(proc: _FakeProc) -> tuple[JanitorStatusOwner, int, int]:
    status_r, status_w = _pipe()
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    return owner, status_r, status_w


def _secondary_success(proc: _FakeProc) -> object:
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
                return _terminate_bound_process(None, proc, pgid=proc.pid)


def test_linux_timeout_zero_does_not_listdir() -> None:
    listed: list[str] = []

    def listdir(path: str) -> list[str]:
        listed.append(path)
        return ["100"]

    with patch("core_tools.provider.process_cleanup.sys.platform", "linux"):
        with patch("core_tools.provider.process_cleanup._linux_proc_available", return_value=True):
            with patch("core_tools.provider.process_cleanup.os.listdir", listdir):
                members = list_process_group_pids(7, timeout=0.0)
    assert members is None
    assert listed == []


def test_linux_listdir_past_deadline_skips_stat_and_is_unverifiable() -> None:
    clock = {"now": 0.0}
    stats: list[int] = []

    def monotonic() -> float:
        return clock["now"]

    def listdir(_path: str) -> list[str]:
        clock["now"] += 0.4
        return ["100", "101"]

    def read_stat(pid: int) -> object:
        stats.append(pid)
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
                        side_effect=read_stat,
                    ):
                        members = list_process_group_pids(7, timeout=0.2)
                        state = wait_process_group_gone(7, timeout=0.0)
    assert members is None
    assert stats == []
    assert state is ProcessGroupState.UNVERIFIABLE


def test_secondary_drain_closes_status_fd() -> None:
    proc = _FakeProc()
    owner, status_r, status_w = _bind(proc)
    result = _secondary_success(proc)
    os.close(status_w)
    assert result is TerminateIdentityResult.FAILED
    assert owner.reap_allowed is False
    assert owner._fd is None
    assert _fd_closed(status_r) is True


def test_secondary_drain_double_close_is_safe() -> None:
    proc = _FakeProc()
    owner, status_r, status_w = _bind(proc)
    result = _secondary_success(proc)
    os.close(status_w)
    owner.close()
    owner.close()
    assert result is TerminateIdentityResult.FAILED
    assert _fd_closed(status_r) is True


def test_secondary_drain_settles_active_reader_then_closes_fd() -> None:
    proc = _FakeProc()
    owner, status_r, status_w = _bind(proc)
    started = threading.Event()
    finished = threading.Event()
    seen: list[object] = []

    def reader() -> None:
        started.set()
        seen.append(owner.read(timeout=0.4))
        finished.set()

    thread = threading.Thread(target=reader)
    thread.start()
    assert started.wait(timeout=1.0)
    time.sleep(0.03)
    result = _secondary_success(proc)
    os.close(status_w)
    thread.join(timeout=1.0)
    assert thread.is_alive() is False
    assert result is TerminateIdentityResult.FAILED
    assert finished.is_set() is True
    assert owner._fd is None
    assert _fd_closed(status_r) is True


def test_repeated_secondary_drain_does_not_grow_fds() -> None:
    baseline = _fd_count()
    counts: list[int] = []
    for _ in range(8):
        proc = _FakeProc()
        owner, _status_r, status_w = _bind(proc)
        result = _secondary_success(proc)
        os.close(status_w)
        assert result is TerminateIdentityResult.FAILED
        assert owner._fd is None
        counts.append(_fd_count())
    assert max(counts) <= baseline + 4


def test_terminate_process_tree_secondary_clean_closes_status_fd() -> None:
    proc = _FakeProc()
    owner, status_r, status_w = _bind(proc)
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
                cleaned = terminate_process_tree(proc, pgid=proc.pid)
    os.close(status_w)
    assert cleaned is False
    assert owner.reap_allowed is False
    assert owner._fd is None
    assert _fd_closed(status_r) is True


def test_cursor_unregisters_only_after_status_fd_closed(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    proc = _FakeProc(pid=5151)
    owner, status_r, status_w = _bind(proc)
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc(
        session_id,
        "planner",
        proc.pid,
        proc=None,
    )
    provider._tracked_turn_procs[proc.pid].proc = proc
    order: list[str] = []

    def unregister(pid: int) -> None:
        order.append("unregister")
        assert owner._fd is None
        assert _fd_closed(status_r) is True
        provider._tracked_turn_procs.pop(pid, None)

    with patch.object(provider, "_unregister_tracked_turn_proc_by_pid", unregister):
        with patch(
            "core_tools.provider.cursor.terminate_verified_process_identity",
            side_effect=lambda identity, proc=None, pgid=None, member_identities=None, timeout=None: (
                _secondary_success(proc)
            ),
        ):
            provider._terminate_tracked_turn_procs()
    os.close(status_w)
    assert order == ["unregister"]
    assert proc.pid not in provider._tracked_turn_procs
    assert _fd_closed(status_r) is True


def test_zombie_ps_timeout_is_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)

    def fake_run(*_args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="ps", timeout=kwargs.get("timeout"))

    with patch("core_tools.provider.process_cleanup._linux_proc_available", return_value=False):
        with patch("core_tools.provider.process_cleanup.os.kill", return_value=None):
            with patch("core_tools.provider.process_cleanup.subprocess.run", side_effect=fake_run):
                state = inspect_pid_liveness(1234, timeout=0.05)
                alive = is_pid_alive(1234, timeout=0.05)
    assert state is PidInspectState.UNVERIFIABLE
    assert alive is True
