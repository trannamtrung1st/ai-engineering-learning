"""Slice 5 rereview 4dae4f6: drain-on-exit, Windows peek fail-closed, one deadline."""

from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _SubprocessStdoutIterator,
    _windows_pipe_has_data,
)
from core_tools.provider.process_identity import (
    ProcessIdentity,
    _current_group_identities,
    inspect_process_identity,
    terminate_verified_process_identity,
)
from tests.conftest import close_and_reap_iterator


def _idle_config() -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": 0.08,
                "max_retries_per_call": 0,
            }
        }
    }


def _provider(tmp_path: Path, runner) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )


def _script_runner(script: str):
    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    return runner


def _system_init(session_id: str) -> str:
    return json.dumps(
        {"type": "system", "subtype": "init", "session_id": session_id}
    )


def _assistant(text: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout drain")
def test_fast_write_and_exit_preserves_json_lines(tmp_path: Path) -> None:
    first = _system_init("chat-fast-exit")
    second = _assistant("done")
    script = (
        "import sys\n"
        f"sys.stdout.write({first!r} + '\\n' + {second!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    provider = _provider(tmp_path, _script_runner(script))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started = time.monotonic()
    events = list(provider.stream_events(session_id))
    assert time.monotonic() - started <= 1.0
    assert provider.canonical_session_id(session_id) == "chat-fast-exit"
    texts = [str(event.get("text") or "") for event in events]
    assert any("done" in text for text in texts) or any(
        "done" in json.dumps(event) for event in events
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout drain")
def test_fast_exit_without_final_newline_preserves_last_line(tmp_path: Path) -> None:
    first = _system_init("chat-no-nl")
    second = _assistant("tail")
    script = (
        "import sys\n"
        f"sys.stdout.write({first!r} + '\\n' + {second!r})\n"
        "sys.stdout.flush()\n"
    )
    provider = _provider(tmp_path, _script_runner(script))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events = list(provider.stream_events(session_id))
    texts = [str(event.get("text") or "") for event in events]
    assert any("tail" in text for text in texts)
    assert provider.canonical_session_id(session_id) == "chat-no-nl"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout drain")
def test_durable_session_id_in_final_exiting_line_is_bound(tmp_path: Path) -> None:
    payload = _system_init("chat-last-line")
    script = (
        "import sys\n"
        f"sys.stdout.write({payload!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    provider = _provider(tmp_path, _script_runner(script))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(session_id))
    assert provider.canonical_session_id(session_id) == "chat-last-line"


def test_windows_peek_named_pipe_failure_is_fail_closed() -> None:
    class FakeDWORD:
        def __init__(self, value: int = 0) -> None:
            self.value = value

    peek = MagicMock(return_value=0)
    fake_kernel32 = types.SimpleNamespace(PeekNamedPipe=peek)
    fake_wintypes = types.ModuleType("ctypes.wintypes")
    fake_wintypes.HANDLE = int
    fake_wintypes.DWORD = FakeDWORD
    fake_wintypes.BOOL = int
    fake_ctypes = types.ModuleType("ctypes")
    fake_ctypes.windll = types.SimpleNamespace(kernel32=fake_kernel32)
    fake_ctypes.wintypes = fake_wintypes
    fake_ctypes.c_void_p = object
    fake_ctypes.POINTER = lambda _typ: object
    fake_ctypes.byref = lambda value: value
    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.get_osfhandle = lambda _fd: 7
    proc = MagicMock()
    proc.poll.return_value = None
    with patch.dict(
        sys.modules,
        {
            "msvcrt": fake_msvcrt,
            "ctypes": fake_ctypes,
            "ctypes.wintypes": fake_wintypes,
        },
    ):
        started = time.monotonic()
        assert _windows_pipe_has_data(3, 0.2, proc=proc) is False
        assert time.monotonic() - started < 0.1
    peek.assert_called()
    assert peek.argtypes is not None
    assert peek.restype is not None


def test_terminate_session_rejects_non_positive_timeout(tmp_path: Path) -> None:
    provider = _provider(tmp_path, _script_runner("print('{}')"))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ValueError, match="positive"):
        provider.terminate_session(session_id, timeout=0)
    with pytest.raises(ValueError, match="positive"):
        provider.terminate_session(session_id, timeout=-0.1)


def test_terminate_session_does_not_enlarge_tiny_timeout(tmp_path: Path) -> None:
    provider = _provider(tmp_path, _script_runner("print('{}')"))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started = time.monotonic()
    provider.terminate_session(session_id, timeout=0.004)
    assert time.monotonic() - started <= 0.2


def test_terminate_verified_inspect_receives_timeout() -> None:
    identity = ProcessIdentity(pid=1, start_time="1")
    timeouts: list[float | None] = []

    def fake_inspect(target, timeout=None):
        del target
        timeouts.append(timeout)
        from core_tools.provider.process_identity import IdentityInspectState

        return IdentityInspectState.GONE

    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        side_effect=fake_inspect,
    ), patch(
        "core_tools.provider.process_identity.read_process_group_id",
        return_value=None,
    ):
        terminate_verified_process_identity(identity, timeout=0.25)
    assert timeouts
    assert timeouts[0] is not None
    assert timeouts[0] <= 0.25


def test_group_identity_reads_share_one_deadline() -> None:
    seen: list[float | None] = []

    def fake_list(pgid, timeout=None):
        del pgid
        seen.append(timeout)
        return [11, 12, 13]

    def fake_read(pid, run_id=None, timeout=None):
        del run_id
        seen.append(timeout)
        time.sleep(0.04)
        return ProcessIdentity(pid=pid, start_time="1")

    with patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        side_effect=fake_list,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        side_effect=fake_read,
    ):
        identities = _current_group_identities(99, timeout=0.2)
    assert identities is not None
    read_timeouts = seen[1:]
    assert read_timeouts[0] is not None
    assert read_timeouts[0] <= 0.2
    assert read_timeouts[-1] is not None
    assert read_timeouts[-1] < read_timeouts[0]


def test_inspect_process_identity_accepts_timeout() -> None:
    identity = ProcessIdentity(pid=os.getpid(), start_time="1")
    state = inspect_process_identity(identity, timeout=0.05)
    assert state is not None


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_iterator_close_reaps_exited_writer(tmp_path: Path) -> None:
    iterator = _SubprocessStdoutIterator(
        [sys.executable, "-c", "print('hi'); raise SystemExit(0)"],
        tmp_path,
    )
    try:
        lines = list(iterator)
        assert any("hi" in line for line in lines)
    finally:
        close_and_reap_iterator(iterator)
