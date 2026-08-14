"""Slice 5 twenty-first re-review regressions (S5-RR21-001 through S5-RR21-003)."""

from __future__ import annotations

import inspect
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from core_tools.provider.cursor import CursorProvider, default_process_runner
from core_tools.provider.errors import ProviderTurnError, ProviderTurnStalledError
from core_tools.provider.process_cleanup import is_pid_alive, terminate_process_tree
from core_tools.provider.process_identity import JANITOR_PARENT_WAIT_SECONDS
from core_tools.provider.session_janitor import (
    JANITOR_CLEANUP_BUDGET_SECONDS,
    CleanupDeadline,
    DrainResult,
    _confirmed_peers,
    _linux_peer_pids,
    _peer_pids,
    _ps_peer_pids,
    _wait_peers_gone,
)


class _FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _linux_stat(pid: int, pgid: int) -> str:
    fields = ["S", "1", str(pgid)] + ["0"] * 16
    return f"{pid} (cmd) {' '.join(fields)}\n"


def _wait_pid_file(path: Path, timeout: float = 2.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.02)
    raise AssertionError(f"pid file was not written: {path}")


def _stubborn_success_script(child_pid_file: Path, *, last: str) -> str:
    return (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.stdout.write('ready\\n')\n"
        f"sys.stdout.write({last!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )


def _fd_count() -> int:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    raise AssertionError("cannot count process file descriptors")


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_successful_turn_with_term_ignoring_descendant_reports_clean(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    last = '{"type":"result","subtype":"success","session_id":"sess-escalated"}'
    lines = list(
        default_process_runner(
            [sys.executable, "-c", _stubborn_success_script(child_pid_file, last=last)],
            tmp_path,
        )
    )
    child_pid = _wait_pid_file(child_pid_file)
    assert last in lines
    assert "ready" in lines
    assert is_pid_alive(child_pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_cancelled_turn_with_term_ignoring_descendant_reports_clean(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.stdout.write('ready\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    holder: list[subprocess.Popen[str] | None] = [None]
    stream = default_process_runner(
        [sys.executable, "-c", script],
        tmp_path,
        active_proc=holder,
    )
    assert next(stream) == "ready"
    child_pid = _wait_pid_file(child_pid_file)
    stream.close()
    proc = holder[0]
    if proc is not None:
        terminate_process_tree(proc)
    assert is_pid_alive(child_pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_unexpected_agent_exit_still_cleans_term_ignoring_descendant(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.stdout.write('ready\\n')\n"
        "sys.stdout.flush()\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        list(default_process_runner([sys.executable, "-c", script], tmp_path))
    child_pid = _wait_pid_file(child_pid_file)
    assert is_pid_alive(child_pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_repeated_teardown_with_term_ignoring_descendant_stays_clean(
    tmp_path: Path,
) -> None:
    last = '{"type":"result","subtype":"success","session_id":"sess-repeat"}'
    baseline = _fd_count()
    for index in range(3):
        child_pid_file = tmp_path / f"child-{index}.pid"
        list(
            default_process_runner(
                [sys.executable, "-c", _stubborn_success_script(child_pid_file, last=last)],
                tmp_path,
            )
        )
        child_pid = _wait_pid_file(child_pid_file)
        assert is_pid_alive(child_pid) is False
    assert _fd_count() <= baseline + 6


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_janitor_status_is_clean_after_safe_group_escalation(tmp_path: Path) -> None:
    from tests.unit.test_slice5_rereview19_fixes import _read_status_fd, _spawn_janitor

    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.exit(0)\n"
    )
    proc, status_r = _spawn_janitor([sys.executable, "-c", script])
    child_pid = _wait_pid_file(child_pid_file)
    time.sleep(0.2)
    proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
    status = _read_status_fd(status_r)
    assert is_pid_alive(child_pid) is False
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert status["agent_code"] == 0
    assert status["stop_requested"] is False


def test_escalation_verifier_does_not_raw_signal_member_pids() -> None:
    from core_tools.provider import session_janitor as janitor

    source = inspect.getsource(janitor)
    assert "os.kill(pid," not in source
    assert "os.kill(peer" not in source
    assert "_signal_listed_peers" not in source
    assert "os.fork()" not in inspect.getsource(janitor.main)


def test_linux_proc_scan_is_unverifiable_when_deadline_expires_mid_scan() -> None:
    clock = _FakeClock(0.0)
    deadline = CleanupDeadline(end=0.05, clock=clock)
    entries = [str(pid) for pid in range(10, 80)]

    def fake_open(path: str, *args: object, **kwargs: object):
        clock.advance(0.01)
        pid = int(Path(path).parent.name)
        return mock_open(read_data=_linux_stat(pid, 99))()

    with patch("core_tools.provider.session_janitor.os.listdir", return_value=entries):
        with patch("builtins.open", side_effect=fake_open):
            assert _linux_peer_pids(99, me=1, deadline=deadline) is None
    assert clock.now <= 0.05 + 0.01


def test_confirmed_peers_are_unverifiable_when_deadline_expires() -> None:
    clock = _FakeClock(0.0)
    deadline = CleanupDeadline(end=0.03, clock=clock)

    def getpgid(_pid: int) -> int:
        clock.advance(0.01)
        return 99

    with patch("core_tools.provider.session_janitor.os.getpgid", side_effect=getpgid):
        assert _confirmed_peers(list(range(10, 40)), 99, me=1, deadline=deadline) is None


def test_darwin_ps_parse_is_unverifiable_when_deadline_expires() -> None:
    class _TickingClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            self.now += 0.01
            return self.now

    deadline = CleanupDeadline(end=0.05, clock=_TickingClock())
    stdout = "\n".join(f"{pid} 99" for pid in range(10, 80)) + "\n"
    with patch(
        "core_tools.provider.session_janitor.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["ps"],
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    ):
        with patch("core_tools.provider.session_janitor.os.getpgid", return_value=99):
            assert _ps_peer_pids(99, me=1, deadline=deadline) is None


def test_wait_peers_gone_stops_when_fake_clock_exhausts_deadline() -> None:
    clock = _FakeClock(0.0)
    deadline = CleanupDeadline(end=0.30, clock=clock)
    remaining_seen: list[float] = []

    def slow(scan_deadline: CleanupDeadline | None = None, **_kwargs: object) -> list[int] | None:
        assert scan_deadline is not None
        remaining = scan_deadline.remaining()
        remaining_seen.append(remaining)
        if remaining <= 0:
            return None
        clock.advance(0.12)
        return [11]

    with patch("core_tools.provider.session_janitor._peer_pids", side_effect=slow):
        result = _wait_peers_gone(deadline, budget=5.0)
    assert result is DrainResult.UNVERIFIABLE
    assert remaining_seen
    assert remaining_seen[-1] <= 0.0
    assert len(remaining_seen) <= 5


def test_peer_pids_forwards_deadline_into_linux_and_confirmation() -> None:
    clock = _FakeClock(1.0)
    deadline = CleanupDeadline(end=1.0, clock=clock)
    assert _peer_pids(deadline) is None


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_real_slow_scan_stays_inside_parent_wait_budget() -> None:
    started = time.monotonic()

    def slow(_deadline: CleanupDeadline | None = None, **_kwargs: object) -> list[int]:
        time.sleep(0.05)
        return [11]

    deadline = CleanupDeadline.after(0.2)
    with patch("core_tools.provider.session_janitor._peer_pids", side_effect=slow):
        result = _wait_peers_gone(deadline, budget=5.0)
    elapsed = time.monotonic() - started
    assert result in {DrainResult.SURVIVORS, DrainResult.UNVERIFIABLE}
    assert elapsed < JANITOR_PARENT_WAIT_SECONDS
    assert elapsed < 2.0


def test_cleanup_budget_covers_escalation_handoff() -> None:
    from core_tools.provider import session_janitor as janitor

    assert JANITOR_CLEANUP_BUDGET_SECONDS >= (
        2 * janitor._PROXY_JOIN_SECONDS
        + janitor._TERM_DRAIN_SECONDS
        + janitor._KILL_DRAIN_SECONDS
        + 2 * janitor._AGENT_WAIT_SECONDS
        + janitor._TAIL_DRAIN_SECONDS
        + 2 * janitor._PS_TIMEOUT_SECONDS
        + janitor._ESCALATE_HANDOFF_SECONDS
    )
    assert JANITOR_PARENT_WAIT_SECONDS >= JANITOR_CLEANUP_BUDGET_SECONDS + 3.0


def test_escalate_command_uses_new_session_not_delayed_helper() -> None:
    from core_tools.provider import session_janitor as janitor

    source = inspect.getsource(janitor._handoff_group_escalation)
    assert "start_new_session" in source
    assert "os.fork()" not in source
    assert "time.sleep" not in inspect.getsource(janitor._run_escalation)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_idle_timeout_with_term_ignoring_descendant_still_closes(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "fork"):
        pytest.skip("fork unavailable")
    child_pid_file = tmp_path / "child.pid"
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.15,
                    "max_retries_per_call": 0,
                }
            }
        },
        workspace=tmp_path,
        runner=default_process_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._set_collect_context(session_id, "planner")
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "open(child_pid_file, 'w', encoding='utf-8').write(str(child))\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    gen = provider._runner([sys.executable, "-c", script], tmp_path)
    assert next(gen) == "ready"
    child_pid = _wait_pid_file(child_pid_file)
    with pytest.raises(ProviderTurnStalledError):
        next(gen)
    try:
        gen.close()
    except ProviderTurnStalledError:
        pass
    assert is_pid_alive(child_pid) is False
