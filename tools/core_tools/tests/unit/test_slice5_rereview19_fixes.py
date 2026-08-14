"""Slice 5 nineteenth re-review regressions (S5-RR19-001 through S5-RR19-008)."""

from __future__ import annotations

import inspect
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import (
    default_process_runner,
    janitor_group_was_cleaned,
    raise_for_cursor_cli_exit,
)
from core_tools.provider.errors import ProviderTurnError
from core_tools.provider.process_cleanup import is_pid_alive
from core_tools.provider.process_identity import (
    JANITOR_PARENT_WAIT_SECONDS,
    _terminate_via_bound_popen,
)
from core_tools.provider.session_janitor import (
    JANITOR_CLEANUP_BUDGET_SECONDS,
    DrainResult,
    _drain_group,
    _proxy_stream,
    _ps_peer_pids,
    decode_janitor_status,
    janitor_command,
)


def _provider_dir() -> str:
    return str(Path(__import__("core_tools.provider.session_janitor", fromlist=["x"]).__file__).parent)


def _wait_pid_file(path: Path, timeout: float = 2.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.02)
    raise AssertionError(f"pid file was not written: {path}")


def _spawn_janitor(
    agent_argv: list[str],
    *,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[str], int]:
    status_r, status_w = os.pipe()
    proc = subprocess.Popen(
        janitor_command(agent_argv, status_fd=status_w),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
        env=env,
        pass_fds=(status_w,),
    )
    os.close(status_w)
    return proc, status_r


def _read_status_fd(status_r: int) -> dict[str, object] | None:
    chunks: list[bytes] = []
    try:
        while True:
            data = os.read(status_r, 4096)
            if not data:
                break
            chunks.append(data)
    except OSError:
        return None
    finally:
        os.close(status_r)
    return decode_janitor_status(b"".join(chunks))


def _spawn_hooked_janitor(
    agent_argv: list[str],
) -> tuple[subprocess.Popen[str], int]:
    status_r, status_w = os.pipe()
    hook = (
        "import os, sys\n"
        f"sys.path.insert(0, {_provider_dir()!r})\n"
        "import session_janitor as janitor\n"
            "janitor._peer_pids = lambda *args, **kwargs: None\n"
        f"raise SystemExit(janitor.main({agent_argv!r}, status_fd={status_w}))\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", hook],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
        pass_fds=(status_w,),
    )
    os.close(status_w)
    return proc, status_r


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_stop_kills_sigterm_ignoring_agent_when_peer_scan_is_unverifiable(
    tmp_path: Path,
) -> None:
    agent_pid_file = tmp_path / "agent.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(agent_pid_file)!r}, 'w', encoding='utf-8').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    proc, status_r = _spawn_hooked_janitor([sys.executable, "-c", script])
    agent_pid = _wait_pid_file(agent_pid_file)
    assert proc.stdin is not None
    proc.stdin.write("STOP\n")
    proc.stdin.close()
    proc.wait(timeout=4)
    status = _read_status_fd(status_r)
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert status["stop_requested"] is True
    assert is_pid_alive(agent_pid) is False
    assert proc.poll() is not None


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_stop_kills_sigterm_ignoring_descendant_when_peer_scan_is_unverifiable(
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
    proc, status_r = _spawn_hooked_janitor([sys.executable, "-c", script])
    assert proc.stdout is not None
    assert "ready" in proc.stdout.readline()
    child_pid = _wait_pid_file(child_pid_file)
    assert proc.stdin is not None
    proc.stdin.write("STOP\n")
    proc.stdin.close()
    proc.wait(timeout=4)
    status = _read_status_fd(status_r)
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert is_pid_alive(child_pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_control_eof_kills_sigterm_ignoring_agent_when_scan_is_unverifiable(
    tmp_path: Path,
) -> None:
    agent_pid_file = tmp_path / "agent.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(agent_pid_file)!r}, 'w', encoding='utf-8').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    proc, status_r = _spawn_hooked_janitor([sys.executable, "-c", script])
    agent_pid = _wait_pid_file(agent_pid_file)
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait(timeout=4)
    status = _read_status_fd(status_r)
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert is_pid_alive(agent_pid) is False


def test_unverifiable_drain_sigkills_direct_agent_before_returning() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    agent = MagicMock()
    agent.poll.return_value = None
    with patch("core_tools.provider.session_janitor._peer_pids", return_value=None):
        with patch("core_tools.provider.session_janitor._signal_group"):
            result = _drain_group(agent)
    agent.kill.assert_called_once()
    assert result is DrainResult.UNVERIFIABLE
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_inherited_empty_peers_env_does_not_hide_stubborn_descendant(
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
        "sys.exit(0)\n"
    )
    env = {**os.environ, "CORE_TOOLS_JANITOR_PEERS": "empty"}
    proc, status_r = _spawn_janitor([sys.executable, "-c", script], env=env)
    child_pid = _wait_pid_file(child_pid_file)
    time.sleep(0.2)
    proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
    status = _read_status_fd(status_r)
    assert is_pid_alive(child_pid) is False
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_peers_env_does_not_force_clean_observation() -> None:
    script = (
        "import json, os, sys, time\n"
        f"sys.path.insert(0, {_provider_dir()!r})\n"
        "import session_janitor as janitor\n"
        "os.environ['CORE_TOOLS_JANITOR_PEERS'] = 'empty'\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "peers = janitor._peer_pids()\n"
        "sys.stdout.write(json.dumps({'child': child, 'peers': peers}))\n"
        "sys.stdout.flush()\n"
        "os.kill(child, 9)\n"
        "os.waitpid(child, 0)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    out, err = proc.communicate(timeout=5)
    assert proc.returncode == 0, err
    payload = json.loads(out)
    assert payload["child"] in payload["peers"]


def test_raise_for_unexpected_agent_sigkill_without_stop() -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        raise_for_cursor_cli_exit(
            0,
            status={
                "agent_code": -signal.SIGKILL,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": False,
            },
        )


def test_raise_for_unexpected_agent_sigsegv_without_stop() -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        raise_for_cursor_cli_exit(
            0,
            status={
                "agent_code": -signal.SIGSEGV,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": False,
            },
        )


def test_stop_requested_signal_death_with_clean_group_is_success() -> None:
    raise_for_cursor_cli_exit(
        -signal.SIGKILL,
        status={
            "agent_code": -signal.SIGTERM,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        },
    )


def test_unexpected_janitor_sigkill_is_not_success_when_status_missing() -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        raise_for_cursor_cli_exit(-signal.SIGKILL, status=None)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_provider_process_exits_unexpectedly_raises(tmp_path: Path) -> None:
    script = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)\n"
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        list(default_process_runner([sys.executable, "-c", script], tmp_path))


def test_parent_wait_covers_janitor_cleanup_budget() -> None:
    assert JANITOR_PARENT_WAIT_SECONDS >= JANITOR_CLEANUP_BUDGET_SECONDS


def test_bound_stop_uses_shared_janitor_parent_wait() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdin.write.return_value = None
    with patch(
        "core_tools.provider.process_identity._request_janitor_stop",
        return_value=True,
    ):
        _terminate_via_bound_popen(proc)
    proc.wait.assert_called()
    waited = proc.wait.call_args.kwargs.get("timeout")
    if waited is None and proc.wait.call_args.args:
        waited = proc.wait.call_args.args[0]
    assert waited is not None
    assert 0 < float(waited) <= JANITOR_PARENT_WAIT_SECONDS


def test_drain_group_does_not_spawn_detached_kill_helper() -> None:
    agent = MagicMock()
    agent.poll.return_value = None
    with patch(
        "core_tools.provider.session_janitor._wait_peers_gone",
        side_effect=[DrainResult.SURVIVORS, DrainResult.CLEAN],
    ):
        with patch("core_tools.provider.session_janitor._peer_pids", return_value=[4242]):
            with patch("core_tools.provider.session_janitor._signal_group"):
                with patch("core_tools.provider.session_janitor.os.kill"):
                    with patch(
                        "core_tools.provider.session_janitor.subprocess.Popen"
                    ) as popen:
                        _drain_group(agent)
    popen.assert_not_called()
    agent.kill.assert_called_once()


def test_janitor_source_has_no_multithreaded_os_fork() -> None:
    from core_tools.provider import session_janitor as janitor

    assert "os.fork()" not in inspect.getsource(janitor._ps_peer_pids)
    assert "os.fork()" not in inspect.getsource(janitor.main)


def test_ps_peer_pids_uses_subprocess_session_not_fork() -> None:
    with patch("core_tools.provider.session_janitor.os.fork") as forked:
        with patch(
            "core_tools.provider.session_janitor.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["ps"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ) as run:
            result = _ps_peer_pids(os.getpgrp(), os.getpid())
    forked.assert_not_called()
    assert run.call_args.kwargs.get("start_new_session") is True
    assert result == []


def test_proxy_thread_preserves_record_order_when_writer_is_delayed() -> None:
    read_fd, write_fd = os.pipe()
    output = bytearray()
    pause = threading.Event()
    resume = threading.Event()

    class Dest:
        def write(self, chunk: bytes) -> None:
            if not output:
                pause.set()
                resume.wait(timeout=2)
            output.extend(chunk)

        def flush(self) -> None:
            return None

    stop = threading.Event()
    src = open(read_fd, "rb", buffering=0)
    thread = threading.Thread(
        target=_proxy_stream,
        args=(src, Dest(), stop),
        daemon=True,
    )
    thread.start()
    os.write(write_fd, b'{"n":1}\n')
    assert pause.wait(timeout=2)
    os.write(write_fd, b'{"n":2}\n{"type":"result","subtype":"success","session_id":"s"}\n')
    os.close(write_fd)
    stop.set()
    resume.set()
    thread.join(timeout=2)
    src.close()
    text = output.decode("utf-8")
    assert text.splitlines() == [
        '{"n":1}',
        '{"n":2}',
        '{"type":"result","subtype":"success","session_id":"s"}',
    ]


def test_main_does_not_read_agent_pipes_during_tail_drain() -> None:
    from core_tools.provider import session_janitor as janitor

    source = inspect.getsource(janitor.main)
    assert "_copy_available(agent.stdout" not in source
    assert "_copy_available(agent.stderr" not in source


def test_agent_exit_124_with_clean_group_is_provider_failure_not_cleanup() -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        raise_for_cursor_cli_exit(
            124,
            status={
                "agent_code": 124,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": False,
            },
        )


def test_agent_exit_125_with_clean_group_is_provider_failure_not_cleanup() -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        raise_for_cursor_cli_exit(
            125,
            status={
                "agent_code": 125,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": False,
            },
        )


def test_positive_agent_failure_with_clean_drain_marks_group_gone() -> None:
    assert (
        janitor_group_was_cleaned(
            1,
            {
                "agent_code": 1,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": False,
            },
        )
        is True
    )


def test_cleanup_unverifiable_and_survivors_are_distinct_from_agent_codes() -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI cleanup failed"):
        raise_for_cursor_cli_exit(
            1,
            status={
                "agent_code": 1,
                "drain": DrainResult.UNVERIFIABLE.value,
                "stop_requested": True,
            },
        )
    with pytest.raises(ProviderTurnError, match="Cursor CLI cleanup failed"):
        raise_for_cursor_cli_exit(
            1,
            status={
                "agent_code": 1,
                "drain": DrainResult.SURVIVORS.value,
                "stop_requested": True,
            },
        )


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_agent_exit_124_clean_group_surfaces_as_provider_failure(tmp_path: Path) -> None:
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        list(
            default_process_runner(
                [sys.executable, "-c", "import sys; sys.exit(124)"],
                tmp_path,
            )
        )
