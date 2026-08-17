"""Slice 5 twentieth re-review regressions (S5-RR20-001 through S5-RR20-004)."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _SubprocessStdoutIterator,
    default_process_runner,
)
from core_tools.provider.errors import ProviderTurnStalledError
from core_tools.provider.process_cleanup import is_pid_alive, terminate_process_tree
from core_tools.provider.process_identity import JANITOR_PARENT_WAIT_SECONDS
from core_tools.provider.session_janitor import (
    JANITOR_CLEANUP_BUDGET_SECONDS,
    CleanupDeadline,
    DrainResult,
    _confirmed_peers,
    _drain_group,
    _kill_agent,
    _linux_peer_pids,
    _peer_pids,
    _ps_peer_pids,
    _signal_group,
    _wait_peers_gone,
)


def _fd_count() -> int:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    raise AssertionError("cannot count process file descriptors")


def _linux_stat(pid: int, pgid: int) -> str:
    fields = ["S", "1", str(pgid)] + ["0"] * 16
    return f"{pid} (cmd) {' '.join(fields)}\n"


def test_confirmed_peer_getpgid_eperm_is_unverifiable() -> None:
    def boom(_pid: int) -> int:
        raise OSError(errno.EPERM, "Operation not permitted")

    with patch("core_tools.provider.session_janitor.os.getpgid", side_effect=boom):
        assert _confirmed_peers([11], 99, me=1) is None


def test_confirmed_peer_getpgid_esrch_is_gone() -> None:
    def missing(_pid: int) -> int:
        raise OSError(errno.ESRCH, "No such process")

    with patch("core_tools.provider.session_janitor.os.getpgid", side_effect=missing):
        assert _confirmed_peers([11], 99, me=1) == []


def test_confirmed_peer_with_different_pgid_is_excluded() -> None:
    with patch("core_tools.provider.session_janitor.os.getpgid", return_value=7):
        assert _confirmed_peers([11], 99, me=1) == []


def test_linux_stat_member_getpgid_eperm_is_unverifiable() -> None:
    def boom(_pid: int) -> int:
        raise OSError(errno.EPERM, "Operation not permitted")

    with patch("core_tools.provider.session_janitor.os.listdir", return_value=["11"]):
        with patch("builtins.open", mock_open(read_data=_linux_stat(11, 99))):
            with patch(
                "core_tools.provider.session_janitor.os.getpgid",
                side_effect=boom,
            ):
                assert _linux_peer_pids(99, me=1) is None


def test_darwin_ps_member_getpgid_eperm_is_unverifiable() -> None:
    def boom(_pid: int) -> int:
        raise OSError(errno.EPERM, "Operation not permitted")

    with patch(
        "core_tools.provider.session_janitor.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["ps"],
            returncode=0,
            stdout="11 99\n",
            stderr="",
        ),
    ):
        with patch(
            "core_tools.provider.session_janitor.os.getpgid",
            side_effect=boom,
        ):
            assert _ps_peer_pids(99, me=1) is None


def test_wait_peers_gone_does_not_report_clean_when_scan_is_unverifiable() -> None:
    deadline = CleanupDeadline.after(0.2)
    with patch("core_tools.provider.session_janitor._peer_pids", return_value=None):
        assert _wait_peers_gone(deadline, budget=1.0) is DrainResult.UNVERIFIABLE


def test_signal_group_skips_when_caller_is_not_session_leader() -> None:
    with patch("core_tools.provider.session_janitor.os.killpg") as killpg:
        with patch("core_tools.provider.session_janitor.os.getpid", return_value=50):
            with patch("core_tools.provider.session_janitor.os.getpgrp", return_value=99):
                _signal_group(signal.SIGTERM)
    killpg.assert_not_called()


def test_signal_group_uses_only_killpg_not_raw_pids() -> None:
    def fake_pgid(pid: int) -> int:
        return 1 if pid == 1 else 99

    with patch("core_tools.provider.session_janitor.os.killpg") as killpg:
        with patch("core_tools.provider.session_janitor.os.kill") as kill:
            with patch(
                "core_tools.provider.session_janitor._peer_pids",
                return_value=[4242],
            ), patch(
                "core_tools.provider.session_janitor.os.getpid", return_value=99
            ), patch(
                "core_tools.provider.session_janitor.os.getpgrp", return_value=99
            ), patch(
                "core_tools.provider.session_janitor.os.getppid", return_value=1
            ), patch(
                "core_tools.provider.session_janitor.os.getpgid", side_effect=fake_pgid
            ):
                _signal_group(signal.SIGTERM)
                _signal_group(signal.SIGKILL)
    assert killpg.call_count == 2
    kill.assert_not_called()


def test_kill_agent_does_not_raw_kill_listed_peer_pids() -> None:
    agent = MagicMock()
    agent.poll.return_value = None
    agent.pid = 99
    with patch("core_tools.provider.session_janitor._peer_pids", return_value=[4242]):
        with patch("core_tools.provider.session_janitor.os.kill") as kill:
            _kill_agent(agent)
    agent.kill.assert_called_once()
    kill.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_stale_enumerated_pid_is_not_signaled_after_exit_and_reuse() -> None:
    original = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    original.kill()
    original.wait(timeout=5)
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pause = threading.Event()
    attempted: list[int] = []

    def tracking_kill(pid: int, _sig: int) -> None:
        attempted.append(pid)
        pause.set()

    try:
        agent = MagicMock()
        agent.poll.return_value = 0
        agent.pid = 1
        with patch("core_tools.provider.session_janitor.os.kill", side_effect=tracking_kill):
            with patch("core_tools.provider.session_janitor.os.killpg"):
                with patch(
                    "core_tools.provider.session_janitor._peer_pids",
                    return_value=[replacement.pid],
                ):
                    _signal_group(signal.SIGTERM)
                    _kill_agent(agent)
                    _signal_group(signal.SIGKILL)
                    _drain_group(agent, CleanupDeadline.after(0.2))
        assert pause.is_set() is False
        assert attempted == []
        assert replacement.poll() is None
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)


def test_second_verification_phase_is_bounded_by_deadline() -> None:
    started = time.monotonic()

    def slow(_deadline: CleanupDeadline | None = None, **_kwargs: object) -> list[int]:
        time.sleep(0.08)
        return [7]

    agent = MagicMock()
    agent.poll.return_value = None
    deadline = CleanupDeadline.after(0.25)
    with patch("core_tools.provider.session_janitor._peer_pids", side_effect=slow):
        with patch("core_tools.provider.session_janitor._signal_group"):
            result = _drain_group(agent, deadline)
    elapsed = time.monotonic() - started
    assert result in {DrainResult.SURVIVORS, DrainResult.UNVERIFIABLE}
    assert elapsed < 0.25 + 0.08 + 1.0
    agent.kill.assert_called()


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_kill_escalation_does_not_signal_reused_member_pid() -> None:
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        agent = MagicMock()
        agent.poll.return_value = None
        agent.pid = 1
        with patch(
            "core_tools.provider.session_janitor._peer_pids",
            return_value=[replacement.pid],
        ):
            _kill_agent(agent)
        assert replacement.poll() is None
        assert is_pid_alive(replacement.pid) is True
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)


def test_cleanup_budget_covers_proxy_joins_scans_and_double_agent_wait() -> None:
    from core_tools.provider import session_janitor as janitor

    expected = (
        2 * janitor._PROXY_JOIN_SECONDS
        + janitor._TERM_DRAIN_SECONDS
        + janitor._KILL_DRAIN_SECONDS
        + 2 * janitor._AGENT_WAIT_SECONDS
        + janitor._TAIL_DRAIN_SECONDS
        + 2 * janitor._PS_TIMEOUT_SECONDS
    )
    assert JANITOR_CLEANUP_BUDGET_SECONDS >= expected
    assert JANITOR_PARENT_WAIT_SECONDS >= JANITOR_CLEANUP_BUDGET_SECONDS + 3.0


def test_ps_timeout_is_capped_by_remaining_deadline() -> None:
    deadline = CleanupDeadline.after(0.35)
    with patch(
        "core_tools.provider.session_janitor.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["ps"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    ) as run:
        _ps_peer_pids(1, 1, deadline=deadline)
    timeout = run.call_args.kwargs.get("timeout")
    assert timeout is not None
    assert timeout <= 0.40
    from core_tools.provider import session_janitor as janitor

    assert timeout < janitor._PS_TIMEOUT_SECONDS


def test_peer_pids_is_unverifiable_when_deadline_elapsed() -> None:
    deadline = CleanupDeadline.after(0)
    time.sleep(0.01)
    assert _peer_pids(deadline) is None


def test_wait_peers_gone_returns_before_parent_budget_with_slow_scans() -> None:
    started = time.monotonic()

    def slow(_deadline: CleanupDeadline | None = None, **_kwargs: object) -> list[int]:
        time.sleep(0.12)
        return [11]

    deadline = CleanupDeadline.after(0.3)
    with patch("core_tools.provider.session_janitor._peer_pids", side_effect=slow):
        result = _wait_peers_gone(deadline, budget=5.0)
    elapsed = time.monotonic() - started
    assert result in {DrainResult.SURVIVORS, DrainResult.UNVERIFIABLE}
    assert elapsed < JANITOR_PARENT_WAIT_SECONDS
    assert elapsed < 2.0


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_parent_wait_receives_terminal_status_before_fallback(tmp_path: Path) -> None:
    from tests.unit.test_slice5_rereview19_fixes import (
        _read_status_fd,
        _spawn_hooked_janitor,
        _wait_pid_file,
    )

    agent_pid_file = tmp_path / "agent.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(agent_pid_file)!r}, 'w', encoding='utf-8').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    proc, status_r = _spawn_hooked_janitor([sys.executable, "-c", script])
    _wait_pid_file(agent_pid_file)
    assert proc.stdin is not None
    proc.stdin.write("STOP\n")
    proc.stdin.close()
    proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
    status = _read_status_fd(status_r)
    assert status is not None
    assert status["drain"] in {
        DrainResult.CLEAN.value,
        DrainResult.UNVERIFIABLE.value,
        DrainResult.SURVIVORS.value,
    }
    assert proc.poll() is not None


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_term_survivors_write_status_before_parent_fallback(tmp_path: Path) -> None:
    from tests.unit.test_slice5_rereview19_fixes import _read_status_fd, _spawn_janitor, _wait_pid_file

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
    assert proc.poll() is not None


def _assert_fd_counts_do_not_grow(counts: list[int], *, baseline: int) -> None:
    assert len(counts) >= 5
    assert counts[-1] <= counts[0]
    assert counts[-1] <= baseline + 4


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_abandoned_provider_stream_closes_status_fd(tmp_path: Path) -> None:
    baseline = _fd_count()
    counts: list[int] = []
    live_script = "import time; print('x', flush=True); time.sleep(8)"
    for _ in range(5):
        holder: list[subprocess.Popen[str] | None] = [None]
        stream = default_process_runner(
            [sys.executable, "-c", live_script],
            tmp_path,
            active_proc=holder,
        )
        assert next(stream) == "x"
        assert isinstance(stream, _SubprocessStdoutIterator)
        proc = holder[0]
        assert proc is not None
        assert proc.poll() is None
        stream.close()
        terminate_process_tree(proc, timeout=0.5)
        counts.append(_fd_count())
    _assert_fd_counts_do_not_grow(counts, baseline=baseline)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_repeated_wrapped_cancellation_does_not_grow_fds(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=default_process_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._set_collect_context(session_id, "planner")
    baseline = _fd_count()
    counts: list[int] = []
    script = "import time; print('ready', flush=True); time.sleep(8)"
    with patch("core_tools.provider.cursor.DEFAULT_TURN_TREE_CLEANUP_SECONDS", 0.5):
        for _ in range(5):
            gen = provider._runner([sys.executable, "-c", script], tmp_path)
            assert next(gen) == "ready"
            gen.close()
            counts.append(_fd_count())
    _assert_fd_counts_do_not_grow(counts, baseline=baseline)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_abandoned_provider_stream_closes_status_fd_without_reading(tmp_path: Path) -> None:
    baseline = _fd_count()
    counts: list[int] = []
    live_script = "import time; print('x', flush=True); time.sleep(8)"
    for _ in range(5):
        holder: list[subprocess.Popen[str] | None] = [None]
        stream = default_process_runner(
            [sys.executable, "-c", live_script],
            tmp_path,
            active_proc=holder,
        )
        assert isinstance(stream, _SubprocessStdoutIterator)
        proc = holder[0]
        assert proc is not None
        assert proc.poll() is None
        stream.close()
        terminate_process_tree(proc, timeout=0.5)
        counts.append(_fd_count())
    _assert_fd_counts_do_not_grow(counts, baseline=baseline)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_idle_timeout_closes_status_fd(tmp_path: Path) -> None:
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
    baseline = _fd_count()
    script = "import time; print('ready', flush=True); time.sleep(30)"
    gen = provider._runner([sys.executable, "-c", script], tmp_path)
    assert next(gen) == "ready"
    with pytest.raises(ProviderTurnStalledError):
        next(gen)
    try:
        gen.close()
    except ProviderTurnStalledError:
        pass
    assert _fd_count() <= baseline + 6


def test_iterator_close_and_del_exist() -> None:
    assert callable(getattr(_SubprocessStdoutIterator, "close"))
    assert callable(getattr(_SubprocessStdoutIterator, "__del__"))
    assert callable(getattr(_SubprocessStdoutIterator, "__enter__"))
    assert callable(getattr(_SubprocessStdoutIterator, "__exit__"))
