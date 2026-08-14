"""Slice 5 twenty-third re-review regressions (S5-RR23-001 through S5-RR23-004)."""

from __future__ import annotations

import errno
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, raise_for_cursor_cli_exit
from core_tools.provider.errors import (
    ProviderTurnCleanupError,
    ProviderTurnError,
)
from core_tools.provider.process_identity import _terminate_via_bound_popen
from core_tools.provider.session_janitor import (
    DrainResult,
    _leader_still_owns_group,
    _process_start_token,
    _run_escalation,
    decode_janitor_status,
    main as janitor_main,
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


@pytest.mark.parametrize("drain", ["survivors", "unverifiable"])
def test_durable_success_plus_cleanup_failure_is_not_retried(
    tmp_path: Path,
    drain: str,
) -> None:
    attempts: list[list[str]] = []

    def runner(argv: list[str], cwd: Path):
        attempts.append(list(argv))
        yield _success_line("chat-durable")
        raise ProviderTurnCleanupError(
            "Cursor CLI cleanup failed",
        )

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderTurnCleanupError, match="cleanup failed"):
        list(provider.stream_events(session_id))
    assert len(attempts) == 1
    assert provider.canonical_session_id(session_id) == "chat-durable"


def test_pending_session_cleanup_failure_does_not_start_second_remote_session(
    tmp_path: Path,
) -> None:
    attempts: list[list[str]] = []

    def runner(argv: list[str], cwd: Path):
        attempts.append(list(argv))
        yield _success_line("chat-first")
        raise ProviderTurnCleanupError("Cursor CLI cleanup failed: survivors")

    provider = _provider(tmp_path, runner)
    pending = provider.start_primary_session("planner", {"goal": "build"})
    assert pending.startswith("cursor-pending-")
    with pytest.raises(ProviderTurnCleanupError):
        list(provider.stream_events(pending))
    assert len(attempts) == 1
    assert not any("--resume" in arg for argv in attempts for arg in argv)


def test_resumed_turn_is_not_replayed_after_remote_completion_and_cleanup_failure(
    tmp_path: Path,
) -> None:
    attempts: list[list[str]] = []

    def runner(argv: list[str], cwd: Path):
        attempts.append(list(argv))
        if len(attempts) == 1:
            yield _success_line("chat-resume")
            return
        yield _success_line("chat-resume")
        raise ProviderTurnCleanupError("Cursor CLI cleanup failed: unverifiable")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_reviewer_session({"goal": "build"})
    list(provider.stream_events(session_id))
    provider.send(session_id, {"text": "continue"})
    with pytest.raises(ProviderTurnCleanupError):
        list(provider.stream_events(session_id))
    assert len(attempts) == 2
    assert "--resume" in attempts[1]



def test_pre_execution_transport_failure_remains_retryable(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ProviderTurnError("broken pipe")
        yield _success_line("chat-retryable")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    list(provider.stream_events(session_id))
    assert attempts["count"] == 2
    assert provider.canonical_session_id(session_id) == "chat-retryable"


def test_raise_for_non_clean_drain_uses_cleanup_error_not_generic_turn_error() -> None:
    with pytest.raises(ProviderTurnCleanupError, match="cleanup failed"):
        raise_for_cursor_cli_exit(
            0,
            status={
                "agent_code": 0,
                "drain": DrainResult.SURVIVORS.value,
                "stop_requested": False,
            },
        )
    with pytest.raises(ProviderTurnCleanupError):
        raise_for_cursor_cli_exit(
            0,
            status={
                "agent_code": 0,
                "drain": DrainResult.UNVERIFIABLE.value,
                "stop_requested": True,
                "cleanup_error": "verifier_signal_failed",
            },
        )


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_stale_leader_identity_does_not_killpg_replacement_group() -> None:
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    status_r, status_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    killpg_calls: list[int] = []

    def record_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append(pgid)
        os.killpg(pgid, sig)

    try:
        with patch(
            "core_tools.provider.session_janitor.os.killpg",
            side_effect=record_killpg,
        ):
            code = _run_escalation(
                pgid=replacement.pid,
                status_fd=status_w,
                handshake_fd=handshake_w,
                go_fd=go_r,
                result_fd=result_w,
                agent_code=0,
                stop_requested=False,
                leader_pid=replacement.pid,
                leader_start="stale-start-token",
            )
        os.close(handshake_r)
        os.close(status_w)
        status = json.loads(_read_fd(status_r).splitlines()[-1])
        result = json.loads(_read_fd(result_r).splitlines()[-1])
        assert code == 1
        assert killpg_calls == []
        assert replacement.poll() is None
        assert status["drain"] == DrainResult.UNVERIFIABLE.value
        assert status["cleanup_error"] == "leader_identity_lost"
        assert result["drain"] == DrainResult.UNVERIFIABLE.value
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_go_then_reaped_leader_skips_killpg_of_reused_pgid() -> None:
    leader = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    leader_start = _process_start_token(leader.pid)
    assert leader_start
    after_go = threading.Event()
    proceed = threading.Event()
    original_await = __import__(
        "core_tools.provider.session_janitor", fromlist=["_await_go"]
    )._await_go

    def gated_await(go_fd: int | None, timeout: float) -> bool:
        ok = original_await(go_fd, timeout)
        if ok:
            after_go.set()
            assert proceed.wait(timeout=2.0)
        return ok

    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    killpg_calls: list[int] = []
    outcome: dict[str, int] = {}

    def record_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append(pgid)

    def run() -> None:
        with patch(
            "core_tools.provider.session_janitor._await_go",
            side_effect=gated_await,
        ):
            with patch(
                "core_tools.provider.session_janitor.os.killpg",
                side_effect=record_killpg,
            ):
                outcome["code"] = _run_escalation(
                    pgid=leader.pid,
                    status_fd=None,
                    handshake_fd=handshake_w,
                    go_fd=go_r,
                    result_fd=result_w,
                    agent_code=0,
                    stop_requested=True,
                    leader_pid=leader.pid,
                    leader_start=leader_start,
                )

    thread = threading.Thread(target=run)
    thread.start()
    assert after_go.wait(timeout=2.0)
    leader.kill()
    leader.wait(timeout=5)
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        proceed.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        os.close(handshake_r)
        _read_fd(result_r)
        assert killpg_calls == []
        assert replacement.poll() is None
        assert outcome["code"] == 1
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)


def test_leader_identity_requires_matching_start_token() -> None:
    assert _leader_still_owns_group(os.getpgrp(), os.getpid(), "wrong-token") is False
    start = _process_start_token(os.getpid())
    assert start
    assert _leader_still_owns_group(os.getpgrp(), os.getpid(), start) is True


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_bound_teardown_reads_status_before_reaping_leader() -> None:
    status_r, status_w = _pipe()
    order: list[str] = []

    class _Stdin:
        def write(self, data: object) -> int:
            return len(data) if isinstance(data, (bytes, str)) else 0

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _Proc:
        stdin = _Stdin()
        pid = 4242

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            order.append("wait")
            return 0

        def kill(self) -> None:
            order.append("kill")

    proc = _Proc()
    proc._core_tools_janitor_status_fd = status_r
    payload = json.dumps(
        {
            "agent_code": 0,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        }
    ).encode("utf-8") + b"\n"

    def publish() -> None:
        time.sleep(0.05)
        order.append("status")
        os.write(status_w, payload)
        os.close(status_w)

    publisher = threading.Thread(target=publish)
    publisher.start()
    _terminate_via_bound_popen(proc)
    publisher.join(timeout=2.0)
    assert order == ["status", "wait"]
    assert proc._core_tools_janitor_status["drain"] == DrainResult.CLEAN.value


@pytest.mark.parametrize("method", ["abort_turn", "terminate_all_sessions"])
def test_cancellation_paths_drop_session_after_cleanup(
    tmp_path: Path,
    method: str,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def runner(argv: list[str], cwd: Path):
        started.set()
        release.wait(timeout=1.0)
        yield from ()

    provider = _provider(tmp_path, runner, retries=0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(provider.stream_events(session_id))
        except BaseException as exc:
            errors.append(exc)

    consumer = threading.Thread(target=consume)
    consumer.start()
    assert started.wait(timeout=1.0)
    if method == "terminate_all_sessions":
        provider.terminate_all_sessions()
    else:
        getattr(provider, method)(session_id)
    release.set()
    consumer.join(timeout=2.0)
    if method != "abort_turn":
        assert provider.list_active_sessions() == []


def test_terminate_session_drops_session_after_turn_cleanup(tmp_path: Path) -> None:
    def runner(argv: list[str], cwd: Path):
        yield _success_line("chat-term")

    provider = _provider(tmp_path, runner, retries=0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(session_id))
    provider.terminate_session(session_id)
    assert provider.list_active_sessions() == []


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_killpg_eperm_publishes_public_unverifiable_status_through_main() -> None:
    status_r, status_w = _pipe()
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)

    def boom(_pgid: int, _sig: int) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    argv = [
        "--status-fd",
        str(status_w),
        "--escalate-pgid",
        "999999",
        "--handshake-fd",
        str(handshake_w),
        "--go-fd",
        str(go_r),
        "--result-fd",
        str(result_w),
        "--agent-code",
        "0",
        "--stop-requested",
        "0",
        "--leader-pid",
        str(os.getpid()),
        "--leader-start",
        _process_start_token(os.getpid()) or "token",
    ]
    with patch(
        "core_tools.provider.session_janitor._leader_still_owns_group",
        return_value=True,
    ):
        with patch("core_tools.provider.session_janitor.os.killpg", side_effect=boom):
            code = janitor_main(argv, status_fd=status_w)
    os.close(handshake_r)
    os.close(status_w)
    status = decode_janitor_status(_read_fd(status_r))
    result = json.loads(_read_fd(result_r).splitlines()[-1])
    assert code == 1
    assert status is not None
    assert status["drain"] == DrainResult.UNVERIFIABLE.value
    assert status["cleanup_error"] == "verifier_signal_failed"
    assert result["ok"] is False
    with pytest.raises(ProviderTurnCleanupError, match="cleanup failed"):
        raise_for_cursor_cli_exit(-signal.SIGKILL, status=status, stderr="")
    with pytest.raises(ProviderTurnError, match="Cursor CLI failed"):
        raise_for_cursor_cli_exit(-signal.SIGKILL, status=None, stderr="")
