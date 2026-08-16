"""Slice 5 rereview d500a84: spawn fail-closed, PGID lineage, isolated janitor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, default_process_runner
from core_tools.provider.errors import ProviderTurnStartupError
from core_tools.provider.process_cleanup import ProcessGroupState, posix_spawn_session_leader
from core_tools.provider.process_identity import IdentityInspectState, ProcessIdentity
from tests.conftest import tracked_turn_proc


def _idle_config(*, idle: float = 0.08, start_timeout: float = 2.0) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
                "agent_start_timeout_seconds": start_timeout,
            }
        }
    }


def _run_isolated_janitor(argv: list[str], *, timeout: float = 8.0):
    kwargs = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    proc = subprocess.Popen(argv, **kwargs)
    chunks: dict[str, str] = {"out": "", "err": ""}

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
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        proc.wait(timeout=2)
        raise
    out_t.join(timeout=1)
    err_t.join(timeout=1)
    if proc.stdin is not None:
        try:
            proc.stdin.close()
        except OSError:
            pass
    return proc.returncode, chunks["out"], chunks["err"]


def _provider(tmp_path: Path, runner=None, *, idle: float = 0.08, start_timeout: float = 2.0) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(idle=idle, start_timeout=start_timeout),
        workspace=tmp_path,
        runner=runner or default_process_runner,
        binary=str(agent),
        skip_probe=True,
    )


def test_posix_spawn_typeerror_fails_closed_without_dropping_setsid() -> None:
    def boom(*_args, **_kwargs):
        raise TypeError("setsid unsupported")

    with patch("core_tools.provider.process_cleanup.os.posix_spawn", boom):
        with pytest.raises(OSError, match="setsid and file_actions"):
            posix_spawn_session_leader([sys.executable, "-c", "pass"])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX spawn")
def test_posix_spawn_restores_caller_inheritable_flags() -> None:
    extra_r, extra_w = os.pipe()
    os.set_inheritable(extra_w, False)

    def fake_spawn(path, argv, env, **kwargs):
        assert os.get_inheritable(extra_w) is True
        return 1

    try:
        with patch("core_tools.provider.process_cleanup.os.posix_spawn", fake_spawn):
            posix_spawn_session_leader(
                [sys.executable, "-c", "pass"],
                inherit_fds=(extra_w,),
            )
        assert os.get_inheritable(extra_w) is False
    finally:
        os.close(extra_r)
        os.close(extra_w)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX spawn")
def test_posix_spawn_closes_non_whitelisted_inheritable_fds() -> None:
    extra_r, extra_w = os.pipe()
    os.set_inheritable(extra_w, True)
    captured: dict[str, object] = {}

    def fake_spawn(path, argv, env, **kwargs):
        captured["file_actions"] = kwargs.get("file_actions")
        captured["setsid"] = kwargs.get("setsid")
        return 1

    try:
        with patch("core_tools.provider.process_cleanup.os.posix_spawn", fake_spawn):
            posix_spawn_session_leader(
                [sys.executable, "-c", "pass"],
                inherit_fds=(),
            )
    finally:
        os.close(extra_r)
        os.close(extra_w)
    actions = captured.get("file_actions") or ()
    closed = {item[1] for item in actions if item and item[0] == os.POSIX_SPAWN_CLOSE}
    assert extra_w in closed
    assert captured.get("setsid") is True


def test_spawned_session_poll_child_process_error_is_not_success() -> None:
    from core_tools.provider.process_cleanup import SpawnedSession

    session = SpawnedSession(pid=4242)
    with patch("os.waitpid", side_effect=ChildProcessError("gone")):
        assert session.poll() == -1
        assert session.returncode == -1


def test_leader_mismatch_and_gone_member_with_live_pgid_is_not_owned(tmp_path: Path) -> None:
    provider = _provider(tmp_path, runner=lambda argv, cwd: iter(()), idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    member = ProcessIdentity(pid=4343, start_time="101")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.member_identities = (leader, member)
    entry.pgid = 4242
    entry.proc = None
    entry.group_observed_gone = False

    def fake_inspect(identity, timeout=None):
        if identity.pid == 4242:
            return IdentityInspectState.IDENTITY_MISMATCH
        return IdentityInspectState.GONE

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        side_effect=fake_inspect,
    ):
        assert provider._tracked_tree_is_live(entry) is False


def test_leader_mismatch_with_live_late_member_stays_owned(tmp_path: Path) -> None:
    provider = _provider(tmp_path, runner=lambda argv, cwd: iter(()), idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    member = ProcessIdentity(pid=4343, start_time="101")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.member_identities = (leader, member)
    entry.pgid = 4242
    entry.proc = None
    entry.group_observed_gone = False

    def fake_inspect(identity, timeout=None):
        if identity.pid == 4343:
            return IdentityInspectState.LIVE_MATCH
        return IdentityInspectState.IDENTITY_MISMATCH

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        side_effect=fake_inspect,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_live_pgid_without_identity_anchors_stays_unresolved(tmp_path: Path) -> None:
    provider = _provider(tmp_path, runner=lambda argv, cwd: iter(()), idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = None
    entry.member_identities = None
    entry.pgid = 4242
    entry.proc = None
    entry.group_observed_gone = False
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_wrap_runner_passes_configured_agent_start_timeout(tmp_path: Path) -> None:
    from core_tools.provider import session_janitor as janitor_mod

    captured: dict[str, object] = {}
    original = janitor_mod.janitor_command

    def wrapped(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    provider = _provider(tmp_path, runner=default_process_runner, start_timeout=7.5)
    with patch.object(janitor_mod, "janitor_command", wrapped):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        try:
            list(provider.stream_events(session_id))
        except Exception:
            pass
    assert captured.get("ready_timeout") == 7.5


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor")
def test_isolated_janitor_preserves_delayed_final_stdout_bytes(tmp_path: Path) -> None:
    from core_tools.provider.session_janitor import janitor_command

    script = """
import json, sys, time
sys.stdout.write(json.dumps({"type": "system", "subtype": "init", "session_id": "sess-late"}) + "\\n")
sys.stdout.flush()
time.sleep(0.15)
sys.stdout.write(json.dumps({"type": "assistant", "text": "tail-ok"}) + "\\n")
sys.stdout.flush()
"""
    code, stdout, stderr = _run_isolated_janitor(
        janitor_command([sys.executable, "-c", script]),
        timeout=8.0,
    )
    assert code == 0, stderr
    assert "sess-late" in stdout
    assert "tail-ok" in stdout


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor")
def test_abort_during_startup_withholds_started_byte(tmp_path: Path) -> None:
    in_wait = threading.Event()
    hold = threading.Event()

    from core_tools.provider.cursor import _SubprocessStdoutIterator

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
