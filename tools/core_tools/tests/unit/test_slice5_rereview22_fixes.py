"""Slice 5 twenty-second re-review regressions (S5-RR22-001 through S5-RR22-003)."""

from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import _SubprocessStdoutIterator
from core_tools.provider.process_cleanup import is_pid_alive
from core_tools.provider.session_janitor import (
    CleanupDeadline,
    DrainResult,
    _handoff_group_escalation,
    _process_start_token,
    _run_escalation,
    _wait_peers_gone,
)


def _pipe() -> tuple[int, int]:
    return os.pipe()


def _read_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    try:
        while True:
            data = os.read(fd, 4096)
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(fd)
    return b"".join(chunks)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_verifier_crash_after_ready_does_not_orphan_or_signal() -> None:
    victim = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    crash = (
        "import os, sys\n"
        "status_fd = handshake_fd = go_fd = result_fd = None\n"
        "args = sys.argv[1:]\n"
        "while len(args) >= 2 and args[0].startswith('--'):\n"
        "    flag, value, args = args[0], args[1], args[2:]\n"
        "    if flag == '--handshake-fd':\n"
        "        handshake_fd = int(value)\n"
        "os.write(handshake_fd, b'READY\\n')\n"
        "raise SystemExit(1)\n"
    )
    try:
        with patch(
            "core_tools.provider.session_janitor._escalation_command",
            side_effect=lambda **kwargs: [sys.executable, "-c", crash]
            + _escalation_argv(**kwargs),
        ):
            outcome = _handoff_group_escalation(
                pgid=victim.pid,
                status_fd=None,
                agent_code=0,
                stop_requested=False,
                deadline=CleanupDeadline.after(2.0),
                leader_pid=os.getpid(),
            )
        assert outcome is None
        assert victim.poll() is None
        assert is_pid_alive(victim.pid) is True
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_killpg_eperm_is_reported_and_does_not_exit_with_survivors() -> None:
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)

    def boom(_pgid: int, _sig: int) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    with patch(
        "core_tools.provider.session_janitor._leader_still_owns_group",
        return_value=True,
    ):
        with patch("core_tools.provider.session_janitor.os.killpg", side_effect=boom):
            code = _run_escalation(
            pgid=999999,
            status_fd=None,
            handshake_fd=handshake_w,
            go_fd=go_r,
            result_fd=result_w,
            agent_code=0,
            stop_requested=False,
            leader_pid=1,
        )
    assert code == 1
    assert os.read(handshake_r, 16).startswith(b"READY")
    os.close(handshake_r)
    result = json.loads(_read_fd(result_r).splitlines()[-1])
    assert result["ok"] is False
    assert result["error"] == "eperm"


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_killpg_oserror_is_reported_and_leaves_target_alive() -> None:
    target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)

    def boom(_pgid: int, _sig: int) -> None:
        raise OSError(errno.EIO, "io error")

    try:
        with patch("core_tools.provider.session_janitor.os.killpg", side_effect=boom):
            _run_escalation(
                pgid=target.pid,
                status_fd=None,
                handshake_fd=handshake_w,
                go_fd=go_r,
                result_fd=result_w,
                agent_code=0,
                stop_requested=False,
                leader_pid=target.pid,
                leader_start=_process_start_token(target.pid),
            )
        os.close(handshake_r)
        result = json.loads(_read_fd(result_r).splitlines()[-1])
        assert result["ok"] is False
        assert result["error"] == "oserror"
        assert target.poll() is None
    finally:
        if target.poll() is None:
            target.kill()
            target.wait(timeout=5)


@pytest.mark.parametrize(
    "drain",
    [DrainResult.SURVIVORS, DrainResult.UNVERIFIABLE],
)
@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_verifier_terminal_survivors_and_unverifiable_are_returned(
    drain: DrainResult,
) -> None:
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    status_r, status_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    with patch("core_tools.provider.session_janitor.os.killpg"):
        with patch(
            "core_tools.provider.session_janitor._wait_peers_gone",
            return_value=drain,
        ):
            with patch(
                "core_tools.provider.session_janitor._leader_still_owns_group",
                return_value=True,
            ):
                _run_escalation(
                pgid=12345,
                status_fd=status_w,
                handshake_fd=handshake_w,
                go_fd=go_r,
                result_fd=result_w,
                agent_code=0,
                stop_requested=False,
                leader_pid=1,
            )
    os.close(handshake_r)
    os.close(status_w)
    result = json.loads(_read_fd(result_r).splitlines()[-1])
    status = json.loads(_read_fd(status_r).splitlines()[-1])
    assert result["drain"] == drain.value
    assert status["drain"] == drain.value


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_handoff_timeout_reaps_helper_before_pgid_reuse() -> None:
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    paused = (
        "import os, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    try:
        started: list[subprocess.Popen[bytes]] = []
        real_popen = subprocess.Popen

        def tracking_popen(*args: object, **kwargs: object):
            proc = real_popen(*args, **kwargs)
            started.append(proc)
            return proc

        with patch(
            "core_tools.provider.session_janitor._escalation_command",
            side_effect=lambda **kwargs: [sys.executable, "-c", paused],
        ):
            with patch(
                "core_tools.provider.session_janitor.subprocess.Popen",
                side_effect=tracking_popen,
            ):
                outcome = _handoff_group_escalation(
                    pgid=replacement.pid,
                    status_fd=None,
                    agent_code=0,
                    stop_requested=False,
                    deadline=CleanupDeadline.after(0.4),
                    leader_pid=os.getpid(),
                )
        assert outcome is None
        assert started
        helper = started[0]
        deadline = time.monotonic() + 2.0
        while helper.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert helper.poll() is not None
        assert replacement.poll() is None
        assert is_pid_alive(replacement.pid) is True
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_no_go_means_verifier_does_not_killpg() -> None:
    target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    try:
        os.close(go_w)
        code = _run_escalation(
            pgid=target.pid,
            status_fd=None,
            handshake_fd=handshake_w,
            go_fd=go_r,
            result_fd=result_w,
            agent_code=0,
            stop_requested=False,
            leader_pid=target.pid,
            go_timeout=0.2,
        )
        os.close(handshake_r)
        os.close(result_r)
        assert code == 0
        assert target.poll() is None
    finally:
        if target.poll() is None:
            target.kill()
            target.wait(timeout=5)


def test_unreaped_leader_is_not_counted_as_survivor() -> None:
    deadline = CleanupDeadline.after(0.5)
    with patch(
        "core_tools.provider.session_janitor._peer_pids",
        return_value=[],
    ) as peers:
        result = _wait_peers_gone(deadline, budget=0.2, pgid=77, me=42, exclude={42})
    assert result is DrainResult.CLEAN
    kwargs = peers.call_args.kwargs
    assert 42 in kwargs.get("exclude", set()) or kwargs.get("me") == 42


def test_parent_reads_status_before_reaping_janitor() -> None:
    source = _SubprocessStdoutIterator._finalize
    import inspect

    text = inspect.getsource(source)
    status_at = text.find("_read_janitor_status")
    wait_at = text.find("self._proc.wait")
    assert status_at != -1
    assert wait_at != -1
    assert status_at < wait_at


def test_main_does_not_voluntarily_return_after_failed_handoff() -> None:
    from core_tools.provider import session_janitor as janitor
    import inspect

    text = inspect.getsource(janitor.main)
    assert "_hold_ownership_anchor" in text
    assert "os.fork()" not in text


def _escalation_argv(
    *,
    pgid: int,
    status_fd: int | None,
    handshake_fd: int,
    go_fd: int,
    result_fd: int,
    agent_code: int,
    stop_requested: bool,
    leader_pid: int,
    leader_start: str | None = None,
    cleanup_budget: float | None = None,
) -> list[str]:
    argv = [
        "--escalate-pgid",
        str(pgid),
        "--handshake-fd",
        str(handshake_fd),
        "--go-fd",
        str(go_fd),
        "--result-fd",
        str(result_fd),
        "--agent-code",
        str(agent_code),
        "--stop-requested",
        "1" if stop_requested else "0",
        "--leader-pid",
        str(leader_pid),
    ]
    if status_fd is not None:
        argv = ["--status-fd", str(status_fd), *argv]
    if leader_start:
        argv.extend(["--leader-start", leader_start])
    if cleanup_budget is not None:
        argv.extend(["--cleanup-budget", f"{max(0.0, cleanup_budget):.6f}"])
    return argv
