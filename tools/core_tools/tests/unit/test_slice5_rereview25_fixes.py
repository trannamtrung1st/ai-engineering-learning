"""Slice 5 twenty-fifth re-review regressions (S5-RR25-001 through S5-RR25-004)."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError
from core_tools.provider.process_identity import (
    TerminateIdentityResult,
    _terminate_bound_process,
    _terminate_via_bound_popen,
)
from core_tools.provider.session_janitor import (
    CleanupDeadline,
    DrainResult,
    JanitorStatusOwner,
    _escalation_command,
    _leader_still_owns_group,
    _run_escalation,
    read_bound_janitor_status,
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


def _error_line(session_id: str | None, message: str = "remote execution failed") -> str:
    payload: dict[str, object] = {"type": "error", "message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return json.dumps(payload)


def _success_line(session_id: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "session_id": session_id,
            "is_error": False,
            "result": "ok",
        }
    )


def _provider(tmp_path: Path, runner, *, retries: int = 2) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": retries}}},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )


class _Stdin:
    def write(self, data: object) -> int:
        return len(data) if isinstance(data, (bytes, str)) else 0

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_error_event_with_durable_id_does_not_retry_first_turn(tmp_path: Path) -> None:
    attempts: list[list[str]] = []

    def runner(argv: list[str], cwd: Path):
        attempts.append(list(argv))
        yield _error_line("chat-durable")

    provider = _provider(tmp_path, runner)
    pending = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderTurnError, match="remote execution failed"):
        list(provider.stream_events(pending))
    assert len(attempts) == 1
    assert provider.canonical_session_id(pending) == "chat-durable"


def test_resumed_error_event_with_expected_durable_id_does_not_replay(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _success_line("chat-resume")
            return
        yield _error_line("chat-resume")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_reviewer_session({"goal": "build"})
    list(provider.stream_events(session_id))
    provider.send(session_id, {"text": "continue"})
    with pytest.raises(ProviderTurnError, match="remote execution failed"):
        list(provider.stream_events(session_id))
    assert attempts["count"] == 2


def test_resumed_mismatched_durable_id_on_error_does_not_replay(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _success_line("chat-resume")
            return
        yield _error_line("chat-other")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_reviewer_session({"goal": "build"})
    list(provider.stream_events(session_id))
    provider.send(session_id, {"text": "continue"})
    with pytest.raises(ProviderTurnError, match="unexpected session id"):
        list(provider.stream_events(session_id))
    assert attempts["count"] == 2


def test_error_event_without_durable_id_remains_retryable(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _error_line(None, "transient provider glitch")
            return
        yield _success_line("chat-retry")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(session_id))
    assert attempts["count"] == 2
    assert provider.canonical_session_id(session_id) == "chat-retry"


def test_poll_does_not_reap_janitor_before_terminal_status() -> None:
    status_r, status_w = _pipe()
    reaped = {"value": False}

    class _Proc:
        stdin = _Stdin()
        pid = 4242

        def poll(self) -> int:
            reaped["value"] = True
            return 0

        def wait(self, timeout: float | None = None) -> int:
            reaped["value"] = True
            return 0

    proc = _Proc()
    owner = JanitorStatusOwner(status_r)
    owner.bind(proc)
    proc._core_tools_janitor_status_owner = owner
    assert proc.poll() is None
    assert reaped["value"] is False
    os.write(
        status_w,
        json.dumps(
            {
                "agent_code": 0,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": True,
            }
        ).encode("utf-8")
        + b"\n",
    )
    os.close(status_w)
    assert read_bound_janitor_status(proc, timeout=1.0)["drain"] == DrainResult.CLEAN.value
    assert proc.poll() == 0
    assert reaped["value"] is True


def test_exited_janitor_with_unread_clean_status_is_terminated() -> None:
    status_r, status_w = _pipe()
    os.write(
        status_w,
        json.dumps(
            {
                "agent_code": 0,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": True,
            }
        ).encode("utf-8")
        + b"\n",
    )
    os.close(status_w)
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    class _Proc:
        stdin = _Stdin()
        pid = 4242

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            return None

    proc = _Proc()
    proc._core_tools_janitor_status_fd = status_r
    try:
        with patch(
            "core_tools.provider.process_identity.drain_owned_process_group",
            return_value=False,
        ) as drain:
            result = _terminate_bound_process(None, proc, pgid=replacement.pid)
        drain.assert_not_called()
        assert result is TerminateIdentityResult.TERMINATED
        assert replacement.poll() is None
        assert isinstance(proc._core_tools_janitor_status, dict)
        assert proc._core_tools_janitor_status["drain"] == DrainResult.CLEAN.value
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_matching_token_after_deadline_does_not_killpg() -> None:
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    killpg_calls: list[int] = []
    clock = {"now": 0.0}

    def late_token(pid: int, deadline: CleanupDeadline | None = None) -> str | None:
        clock["now"] = 10.0
        return "1.000001"

    with patch(
        "core_tools.provider.session_janitor.os.getpgid",
        return_value=700,
    ):
        with patch(
            "core_tools.provider.session_janitor._process_start_token",
            side_effect=late_token,
        ):
            with patch(
                "core_tools.provider.session_janitor.os.killpg",
                side_effect=lambda pgid, sig: killpg_calls.append(pgid),
            ):
                with patch(
                    "core_tools.provider.session_janitor.time.monotonic",
                    side_effect=lambda: clock["now"],
                ):
                    code = _run_escalation(
                        pgid=700,
                        status_fd=None,
                        handshake_fd=handshake_w,
                        go_fd=go_r,
                        result_fd=result_w,
                        agent_code=0,
                        stop_requested=False,
                        leader_pid=700,
                        leader_start="1.000001",
                    )
    os.close(handshake_r)
    result = json.loads(_read_fd(result_r).splitlines()[-1])
    assert code == 1
    assert killpg_calls == []
    assert result["drain"] == DrainResult.UNVERIFIABLE.value


def test_linux_and_darwin_start_token_recheck_deadline_after_lookup() -> None:
    from core_tools.provider import session_janitor as janitor

    linux = inspect.getsource(janitor._linux_process_start_token)
    darwin = inspect.getsource(janitor._darwin_process_start_token)
    owns = inspect.getsource(janitor._leader_still_owns_group)
    escalate = inspect.getsource(janitor._run_escalation)
    assert linux.rfind("_deadline_expired") > linux.find("fields[19]")
    assert darwin.rfind("_deadline_expired") > darwin.find("proc_pidinfo")
    assert owns.rfind("_deadline_expired") > owns.find("current !=")
    assert "killpg" in escalate
    assert escalate.find("_deadline_expired") < escalate.find("os.killpg")


def test_escalation_command_does_not_lookup_start_token_without_deadline() -> None:
    source = inspect.getsource(_escalation_command)
    assert "_process_start_token" not in source
    argv = _escalation_command(
        pgid=1,
        status_fd=None,
        handshake_fd=2,
        go_fd=3,
        result_fd=4,
        agent_code=0,
        stop_requested=False,
        leader_pid=7,
        leader_start=None,
    )
    assert argv[argv.index("--leader-start") + 1] == ""


def test_leader_ownership_false_when_lookup_returns_token_after_deadline() -> None:
    clock = {"now": 0.0}
    deadline = CleanupDeadline(end=1.0, clock=lambda: clock["now"])

    def late(_pid: int, deadline: CleanupDeadline | None = None) -> str | None:
        clock["now"] = 2.0
        return "1.000001"

    with patch(
        "core_tools.provider.session_janitor.os.getpgid",
        return_value=1,
    ), patch(
        "core_tools.provider.session_janitor.os.getsid",
        return_value=1,
    ):
        with patch(
            "core_tools.provider.session_janitor._process_start_token",
            side_effect=late,
        ):
            assert _leader_still_owns_group(1, 1, "1.000001", deadline=deadline) is False
