"""Slice 5 rereview c67af97: idle handshake, zombie reap, PGID ownership, framing."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import (
    MAX_STREAM_JSON_RECORD_BYTES,
    CursorProvider,
    default_process_runner,
    _SubprocessStdoutIterator,
)
from core_tools.provider.errors import (
    ProviderStreamRecordTooLargeError,
    ProviderTurnStalledError,
)
from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    inspect_pid_liveness,
    is_pid_alive,
    is_pid_reaped,
    terminate_pid_tree,
)
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    drain_owned_process_group,
    read_process_identity,
)
from tests.conftest import close_and_reap_iterator, tracked_turn_proc


def _idle_config(idle: float) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
            }
        }
    }


def _provider(tmp_path: Path, runner=None, idle: float = 0.08) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner or (lambda argv, cwd: iter(())),
        binary=str(agent),
        skip_probe=True,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor handshake")
def test_first_idle_window_starts_after_agent_child_handshake(tmp_path: Path) -> None:
    started_at = tmp_path / "started"
    handshake_at: dict[str, float] = {}
    idle_armed_at: dict[str, float] = {}
    original_wait = _SubprocessStdoutIterator.wait_agent_started

    def wait_and_mark(self, timeout=None):
        original_wait(self, timeout=timeout)
        handshake_at["t"] = time.monotonic()

    original_idle = CursorProvider._iter_stream_with_idle_timeout

    def idle_and_mark(*args, **kwargs):
        stream = args[0]
        if not hasattr(stream, "read_nonempty_line") and len(args) > 1:
            stream = args[1]
        idle_armed_at["t"] = time.monotonic()
        idle_armed_at["deadline"] = kwargs.get("deadline")
        return original_idle(stream, **kwargs)

    (tmp_path / "agent").write_text("", encoding="utf-8")
    script = (
        "import json, sys, time\n"
        f"open({str(started_at)!r}, 'w').write(str(time.monotonic()))\n"
        "time.sleep(0.15)\n"
        "print(json.dumps({'type': 'assistant', 'text': 'ok'}), flush=True)\n"
    )
    provider = CursorProvider(
        _idle_config(0.5),
        workspace=tmp_path,
        runner=default_process_runner,
        binary=str(tmp_path / "agent"),
        skip_probe=True,
    )
    with patch.object(_SubprocessStdoutIterator, "wait_agent_started", wait_and_mark):
        with patch.object(CursorProvider, "_iter_stream_with_idle_timeout", idle_and_mark):
            lines = list(provider._runner([sys.executable, "-c", script], tmp_path))
    assert any("ok" in line for line in lines)
    assert started_at.exists()
    assert handshake_at["t"] <= idle_armed_at["t"]
    assert idle_armed_at["deadline"] is not None
    assert idle_armed_at["deadline"] >= handshake_at["t"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX idle stall")
def test_silent_agent_after_handshake_still_stalls(tmp_path: Path) -> None:
    script = "import time; time.sleep(60)\n"
    provider = _provider(tmp_path, idle=0.08)
    from core_tools.provider.cursor import default_process_runner

    gen = provider._wrap_runner(default_process_runner)(
        [sys.executable, "-c", script], tmp_path
    )
    started = time.monotonic()
    with pytest.raises(ProviderTurnStalledError):
        next(gen)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.07
    try:
        gen.close()
    except Exception:
        pass


@pytest.mark.parametrize("nbytes", [4 * 1024, 8 * 1024, 64 * 1024])
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_supported_stream_json_record_sizes_are_accepted(
    tmp_path: Path, nbytes: int
) -> None:
    payload = "x" * nbytes
    line = json.dumps({"type": "assistant", "text": payload})
    script = (
        "import sys\n"
        f"sys.stdout.write({line!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        assert next(iterator) == line
        with pytest.raises(StopIteration):
            next(iterator)
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_record_over_max_stream_bytes_is_rejected_even_with_newline(
    tmp_path: Path,
) -> None:
    payload = "x" * (MAX_STREAM_JSON_RECORD_BYTES + 8)
    line = json.dumps({"type": "assistant", "text": payload})
    assert len(line) > MAX_STREAM_JSON_RECORD_BYTES
    script = (
        "import sys\n"
        f"sys.stdout.write({line!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        with pytest.raises(ProviderStreamRecordTooLargeError):
            next(iterator)
    finally:
        close_and_reap_iterator(iterator)


def test_oversized_stream_record_is_not_retried(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def runner(argv, cwd):
        del argv, cwd
        attempts["n"] += 1
        raise ProviderStreamRecordTooLargeError("stream-json record exceeded limit")

    (tmp_path / "agent").write_text("", encoding="utf-8")
    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.0,
                    "max_retries_per_call": 2,
                }
            }
        },
        workspace=tmp_path,
        runner=runner,
        binary=str(tmp_path / "agent"),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    session = provider._sessions[session_id]
    with pytest.raises(ProviderStreamRecordTooLargeError):
        provider._collect_turn_once(session_id, session, [sys.executable, "-c", "pass"])
    assert attempts["n"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_terminate_pid_tree_reaps_direct_zombie_child() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    try:
        assert terminate_pid_tree(proc.pid) is True
        assert is_pid_reaped(proc.pid)
        assert not is_pid_alive(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_drain_reaps_owned_zombie_before_declaring_group_gone() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = read_process_identity(proc.pid)
    assert identity is not None
    pgid = os.getpgid(proc.pid)
    try:
        os.kill(proc.pid, signal.SIGKILL)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and is_pid_alive(proc.pid):
            time.sleep(0.01)
        assert drain_owned_process_group(
            pgid=pgid,
            leader_identity=identity,
            known_identities=[identity],
            timeout=2.0,
        ) or is_pid_reaped(proc.pid)
        assert is_pid_reaped(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_idle_timeout_kills_sigterm_ignoring_descendant(tmp_path: Path) -> None:
    from core_tools.provider.cursor import default_process_runner
    from core_tools.provider.process_cleanup import is_pid_alive as live

    child_pid_file = tmp_path / "child.pid"
    provider = _provider(tmp_path, idle=0.15)
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
    gen = provider._wrap_runner(default_process_runner)(
        [sys.executable, "-c", script], tmp_path
    )
    assert next(gen) == "ready"
    deadline = time.monotonic() + 2.0
    child_pid = 0
    while time.monotonic() < deadline:
        if child_pid_file.exists() and child_pid_file.read_text().strip().isdigit():
            child_pid = int(child_pid_file.read_text().strip())
            break
        time.sleep(0.02)
    assert child_pid
    with pytest.raises(ProviderTurnStalledError):
        next(gen)
    try:
        gen.close()
    except Exception:
        pass
    gone_deadline = time.monotonic() + 5.0
    while time.monotonic() < gone_deadline and live(child_pid):
        time.sleep(0.05)
    assert inspect_pid_liveness(child_pid) is PidInspectState.GONE


def test_live_pgid_without_identity_or_janitor_is_not_owned(tmp_path: Path) -> None:
    provider = _provider(tmp_path, idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.pgid = 4242
    entry.member_identities = (leader,)
    entry.proc = None
    entry.group_observed_gone = False
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.IDENTITY_MISMATCH,
    ):
        assert provider._tracked_tree_is_live(entry) is False


def test_janitor_anchor_keeps_late_child_tree_live(tmp_path: Path) -> None:
    provider = _provider(tmp_path, idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 4242
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.pgid = 4242
    entry.member_identities = (leader,)
    entry.proc = proc
    entry.group_observed_gone = False
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        assert provider._tracked_tree_is_live(entry) is True
