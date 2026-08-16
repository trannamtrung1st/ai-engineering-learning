"""Slice 5 rereview 6634f6e: startup ownership, handshake readiness, PGID lineage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _SubprocessStdoutIterator,
    default_process_runner,
)
from core_tools.provider.errors import ProviderTurnStartupError
from core_tools.provider.process_cleanup import PidInspectState, ProcessGroupState
from core_tools.provider.process_identity import IdentityInspectState, ProcessIdentity
from tests.conftest import tracked_turn_proc


def _idle_config(idle: float) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
                "agent_start_timeout_seconds": 2.0,
            }
        }
    }


def _provider(tmp_path: Path, runner=None, idle: float = 0.08) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner or default_process_runner,
        binary=str(agent),
        skip_probe=True,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor")
def test_janitor_is_tracked_before_started_byte(tmp_path: Path) -> None:
    in_wait = threading.Event()
    release = threading.Event()
    seen: dict[str, object] = {}
    original_wait = _SubprocessStdoutIterator.wait_agent_started

    def block_wait(self, timeout=None):
        seen["started"] = bool(getattr(self, "_agent_started", False))
        seen["pid"] = getattr(self._proc, "pid", None)
        in_wait.set()
        release.wait(timeout=2.0)
        return original_wait(self, timeout=timeout)

    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            with patch.object(_SubprocessStdoutIterator, "wait_agent_started", block_wait):
                list(provider.stream_events(session_id))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    assert in_wait.wait(timeout=2.0)
    tracked = dict(provider._tracked_turn_procs)
    release.set()
    thread.join(timeout=3.0)
    assert seen["started"] is False
    assert seen["pid"] in tracked
    del errors


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor")
def test_abort_during_startup_reaps_tracked_janitor(tmp_path: Path) -> None:
    in_wait = threading.Event()
    hold = threading.Event()

    def block_wait(self, timeout=None):
        in_wait.set()
        hold.wait(timeout=2.0)
        raise ProviderTurnStartupError("started byte withheld")

    provider = _provider(tmp_path, idle=2.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            with patch.object(_SubprocessStdoutIterator, "wait_agent_started", block_wait):
                list(provider.stream_events(session_id))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    assert in_wait.wait(timeout=2.0)
    assert provider._tracked_turn_procs
    provider.abort_turn(session_id, timeout=1.0)
    hold.set()
    thread.join(timeout=3.0)
    assert provider._tracked_turn_procs == {}
    del errors


def test_reused_pgid_with_mismatched_identities_is_not_owned(tmp_path: Path) -> None:
    provider = _provider(tmp_path, runner=lambda argv, cwd: iter(()), idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.member_identities = (leader,)
    entry.pgid = 4242
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


def test_late_child_gone_identities_with_live_group_are_not_pinned(tmp_path: Path) -> None:
    provider = _provider(tmp_path, runner=lambda argv, cwd: iter(()), idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.member_identities = (leader,)
    entry.pgid = 4242
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
        return_value=IdentityInspectState.GONE,
    ):
        assert provider._tracked_tree_is_live(entry) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor")
def test_started_byte_arrives_after_proxy_threads_start(tmp_path: Path) -> None:
    from core_tools.provider.session_janitor import janitor_command

    started_r, started_w = os.pipe()
    script = (
        "import json, sys\n"
        "print(json.dumps({'type': 'assistant', 'text': 'ok'}), flush=True)\n"
    )
    argv = janitor_command(
        [sys.executable, "-c", script],
        started_fd=started_w,
        ready_timeout=2.0,
    )
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        pass_fds=(started_w,),
    )
    os.close(started_w)
    try:
        proc.communicate(timeout=5)
        byte = os.read(started_r, 8)
    finally:
        os.close(started_r)
        if proc.poll() is None:
            os.killpg(proc.pid, 9)
            proc.wait(timeout=2)
    assert proc.returncode == 0
    assert byte[:1] == b"1"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor")
def test_isolated_janitor_preserves_final_stdout_record(tmp_path: Path) -> None:
    from core_tools.provider.session_janitor import janitor_command

    record = json.dumps({"type": "assistant", "text": "tail-ok"}) + "\n"
    script = f"import sys; sys.stdout.write({record!r}); sys.stdout.flush()\n"
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    chunks = {"out": "", "err": ""}

    def read_out() -> None:
        if proc.stdout is not None:
            chunks["out"] = proc.stdout.read()

    def read_err() -> None:
        if proc.stderr is not None:
            chunks["err"] = proc.stderr.read()

    out_t = threading.Thread(target=read_out, daemon=True)
    err_t = threading.Thread(target=read_err, daemon=True)
    out_t.start()
    err_t.start()
    proc.wait(timeout=8)
    out_t.join(timeout=1)
    err_t.join(timeout=1)
    assert proc.returncode == 0, chunks["err"]
    assert "tail-ok" in chunks["out"]


def test_zero_cleanup_budget_does_not_signal_group() -> None:
    from core_tools.provider.session_janitor import _run_escalation

    signaled: list[tuple[int, int]] = []
    go_r, go_w = os.pipe()
    result_r, result_w = os.pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)

    def fake_killpg(pgid, sig):
        signaled.append((pgid, sig))

    try:
        with patch("core_tools.provider.session_janitor.os.killpg", side_effect=fake_killpg):
            assert (
                _run_escalation(
                    pgid=4242,
                    status_fd=None,
                    handshake_fd=None,
                    go_fd=go_r,
                    result_fd=result_w,
                    agent_code=0,
                    stop_requested=False,
                    leader_pid=1,
                    cleanup_budget=0.0,
                )
                == 0
            )
    finally:
        for fd in (go_r, result_r, result_w):
            try:
                os.close(fd)
            except OSError:
                pass
    assert signaled == []


def test_wait_agent_started_select_error_is_startup_failure() -> None:
    iterator = _SubprocessStdoutIterator.__new__(_SubprocessStdoutIterator)
    iterator._started_read_fd = 3
    iterator._agent_started = False
    iterator._proc = MagicMock()
    iterator._proc.poll.return_value = None
    iterator._proc.pid = os.getpid()
    with patch(
        "core_tools.provider.cursor.select.select",
        side_effect=OSError("bad fd"),
    ), patch(
        "core_tools.provider.cursor.inspect_pid_liveness",
        return_value=PidInspectState.LIVE,
    ):
        with pytest.raises(ProviderTurnStartupError):
            iterator.wait_agent_started(timeout=0.2)
    iterator._started_read_fd = None
