"""Slice 5 twenty-fourth re-review regressions (S5-RR24-001 through S5-RR24-005)."""

from __future__ import annotations

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
from core_tools.provider.errors import ProviderTurnCleanupError, ProviderTurnError
from core_tools.provider.process_identity import (
    TerminateIdentityResult,
    _terminate_bound_process,
)
from core_tools.provider.session_janitor import (
    CleanupDeadline,
    DrainResult,
    _leader_still_owns_group,
    _process_start_token,
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


def test_resumed_turn_retries_broken_pipe_before_any_output(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _success_line("chat-resume")
            return
        if attempts["count"] == 2:
            raise ProviderTurnError("broken pipe")
        yield _success_line("chat-resume")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_reviewer_session({"goal": "build"})
    list(provider.stream_events(session_id))
    provider.send(session_id, {"text": "continue"})
    list(provider.stream_events(session_id))
    assert attempts["count"] == 3


def test_resumed_primary_turn_retries_pre_output_transport_failure(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _success_line("chat-primary")
            return
        if attempts["count"] == 2:
            raise ProviderTurnError("broken pipe")
        yield _success_line("chat-primary")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    list(provider.stream_events(session_id))
    provider.resume_primary_session(session_id, {"goal": "build"}, role="planner")
    list(provider.stream_events(session_id))
    assert attempts["count"] == 3


def test_resumed_turn_does_not_replay_after_current_turn_result(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _success_line("chat-resume")
            return
        yield _success_line("chat-resume")
        raise ProviderTurnError("late parse failure")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_reviewer_session({"goal": "build"})
    list(provider.stream_events(session_id))
    provider.send(session_id, {"text": "continue"})
    with pytest.raises(ProviderTurnError, match="late parse failure"):
        list(provider.stream_events(session_id))
    assert attempts["count"] == 2


def test_transient_pre_output_failure_still_retries(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ProviderTurnError("broken pipe")
        yield _success_line("chat-first")

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(session_id))
    assert attempts["count"] == 2


def test_cleanup_error_never_retries_on_resumed_or_transient_session(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        yield _success_line("chat-clean")
        raise ProviderTurnCleanupError("Cursor CLI cleanup failed: survivors")

    provider = _provider(tmp_path, runner)
    pending = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderTurnCleanupError):
        list(provider.stream_events(pending))
    assert attempts["count"] == 1


def test_same_second_start_tokens_do_not_match() -> None:
    assert _leader_still_owns_group(1, 1, "100.000001") is False
    with patch(
        "core_tools.provider.session_janitor.os.getpgid",
        return_value=1,
    ):
        with patch(
            "core_tools.provider.session_janitor._process_start_token",
            return_value="100.000002",
        ):
            assert _leader_still_owns_group(1, 1, "100.000001") is False
        with patch(
            "core_tools.provider.session_janitor._process_start_token",
            return_value="100.000001",
        ):
            assert _leader_still_owns_group(1, 1, "100.000001") is True


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_same_second_identity_mismatch_does_not_killpg() -> None:
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    killpg_calls: list[int] = []

    def record_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append(pgid)

    with patch(
        "core_tools.provider.session_janitor.os.getpgid",
        return_value=700,
    ):
        with patch(
            "core_tools.provider.session_janitor._process_start_token",
            return_value="1786680042.000002",
        ):
            with patch(
                "core_tools.provider.session_janitor.os.killpg",
                side_effect=record_killpg,
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
                    leader_start="1786680042.000001",
                )
    os.close(handshake_r)
    result = json.loads(_read_fd(result_r).splitlines()[-1])
    assert code == 1
    assert killpg_calls == []
    assert result["drain"] == DrainResult.UNVERIFIABLE.value


def test_unavailable_start_token_is_fail_closed() -> None:
    with patch(
        "core_tools.provider.session_janitor._process_start_token",
        return_value=None,
    ):
        assert _leader_still_owns_group(os.getpgrp(), os.getpid(), "token") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="strong Darwin token is macOS-only")
def test_darwin_start_token_has_subsecond_kernel_precision() -> None:
    token = _process_start_token(os.getpid())
    assert token is not None
    seconds, _, fraction = token.partition(".")
    assert seconds.isdigit()
    assert fraction.isdigit()
    assert len(fraction) >= 1
    assert "Fri" not in token
    assert "Aug" not in token


def test_process_start_token_does_not_use_ps_lstart() -> None:
    import inspect
    from core_tools.provider import session_janitor as janitor

    text = inspect.getsource(janitor._process_start_token)
    darwin = inspect.getsource(janitor._darwin_process_start_token)
    assert "lstart" not in text
    assert "lstart" not in darwin
    assert "proc_pidinfo" in darwin


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_stalled_start_token_lookup_expires_before_deadline_without_killpg() -> None:
    handshake_r, handshake_w = _pipe()
    go_r, go_w = _pipe()
    result_r, result_w = _pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    killpg_calls: list[int] = []
    clock = {"now": 0.0}

    def stall(pid: int, deadline: CleanupDeadline | None = None) -> str | None:
        if deadline is None or deadline.remaining() <= 0:
            return None
        clock["now"] = deadline.end
        return None

    with patch(
        "core_tools.provider.session_janitor._process_start_token",
        side_effect=stall,
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
                    pgid=os.getpgrp(),
                    status_fd=None,
                    handshake_fd=handshake_w,
                    go_fd=go_r,
                    result_fd=result_w,
                    agent_code=0,
                    stop_requested=False,
                    leader_pid=os.getpid(),
                    leader_start="1.1",
                )
    os.close(handshake_r)
    result = json.loads(_read_fd(result_r).splitlines()[-1])
    assert code == 1
    assert killpg_calls == []
    assert result["drain"] == DrainResult.UNVERIFIABLE.value


def test_reap_verifier_signals_process_group() -> None:
    import inspect
    from core_tools.provider import session_janitor as janitor

    text = inspect.getsource(janitor._reap_verifier)
    assert "killpg" in text


def test_concurrent_status_readers_share_one_fd_and_same_payload() -> None:
    status_r, status_w = _pipe()

    class _Proc:
        pass

    proc = _Proc()
    proc._core_tools_janitor_status_fd = status_r
    payload = {
        "agent_code": 0,
        "drain": DrainResult.CLEAN.value,
        "stop_requested": True,
    }
    results: list[dict[str, object] | None] = []
    barrier = threading.Barrier(2)

    def reader() -> None:
        barrier.wait()
        results.append(read_bound_janitor_status(proc, timeout=2.0))

    threads = [threading.Thread(target=reader) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    os.write(status_w, json.dumps(payload).encode("utf-8") + b"\n")
    os.close(status_w)
    for thread in threads:
        thread.join(timeout=2.0)
    assert results == [payload, payload]


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_clean_janitor_status_is_authoritative_after_pgid_reuse() -> None:
    status_r, status_w = _pipe()
    replacement = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    payload = json.dumps(
        {
            "agent_code": 0,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        }
    ).encode("utf-8") + b"\n"

    class _Proc:
        stdin = _Stdin()
        pid = 4242

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            return None

    proc = _Proc()
    proc.poll = lambda: None  # type: ignore[method-assign]
    waited = {"done": False}

    def wait(timeout: float | None = None) -> int:
        waited["done"] = True
        proc.poll = lambda: 0  # type: ignore[method-assign]
        return 0

    proc.wait = wait  # type: ignore[method-assign]
    proc._core_tools_janitor_status_fd = status_r
    os.write(status_w, payload)
    os.close(status_w)
    try:
        with patch(
            "core_tools.provider.process_identity.drain_owned_process_group",
            return_value=False,
        ) as drain:
            result = _terminate_bound_process(
                None,
                proc,
                pgid=replacement.pid,
            )
        assert waited["done"] is True
        drain.assert_not_called()
        assert result is TerminateIdentityResult.TERMINATED
        assert replacement.poll() is None
    finally:
        if replacement.poll() is None:
            replacement.kill()
            replacement.wait(timeout=5)
