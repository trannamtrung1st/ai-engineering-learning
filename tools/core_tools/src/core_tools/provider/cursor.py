"""Thin Cursor CLI provider adapter (proposal §16)."""

from __future__ import annotations

import json
import os
import queue
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from core_tools.provider.cursor_session_errors import (
    classify_cursor_session_failure,
    reclassify_provider_turn_error,
)
from core_tools.provider.errors import (
    ProviderBinaryNotFoundError,
    ProviderError,
    ProviderSessionError,
    ProviderSessionMismatchError,
    ProviderSessionNotFoundError,
    ProviderSessionTerminationError,
    ProviderTurnCleanupError,
    ProviderTurnError,
    ProviderTurnStalledError,
    ProviderTurnStartupError,
    ProviderStreamRecordTooLargeError,
    ProviderLifecycleTimeoutError,
    ProviderUnsupportedPlatformError,
)
from core_tools.provider.events import (
    format_manifest_prompt,
    format_request_prompt,
    normalize_cursor_event,
)
from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    inspect_pid_liveness,
    is_pid_alive,
    list_process_group_pids,
    read_process_group_id,
    process_group_state,
    terminate_process_tree,
)
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    _remaining_fn,
    capture_process_group_identities,
    current_process_group_lineage,
    inspect_process_identity,
    IdentityInspectState,
    GroupLineageState,
    PROVIDER_OWNER_ENV_VAR,
    process_identities_from_termination_record,
    process_identity_is_live,
    process_identity_token,
    read_process_identity,
    read_process_start_time,
    terminate_verified_process_identity,
)
from core_tools.provider.session_janitor import (
    DrainResult,
    JANITOR_PARENT_WAIT_SECONDS,
    JanitorStatusOwner,
    read_bound_janitor_status,
)

_CURSOR_TRANSIENT_SESSION_PREFIX = "cursor-pending-"
DEFAULT_TURN_IDLE_TIMEOUT_SECONDS = 2.0
DEFAULT_AGENT_START_TIMEOUT_SECONDS = 5.0
DEFAULT_TURN_TREE_CLEANUP_SECONDS = 2.0
MAX_STREAM_JSON_RECORD_BYTES = 256 * 1024
_MAX_IDLE_RESCUE_BYTES = MAX_STREAM_JSON_RECORD_BYTES
_STDERR_TAIL_MAX_BYTES = 64 * 1024


def max_stream_json_record_bytes(config: Mapping[str, Any] | None) -> int:
    """Return the Cursor stream-json line cap from ``limits.provider``."""

    if not isinstance(config, Mapping):
        return MAX_STREAM_JSON_RECORD_BYTES
    provider_limits = (config.get("limits") or {}).get("provider") or {}
    if not isinstance(provider_limits, Mapping):
        return MAX_STREAM_JSON_RECORD_BYTES
    raw = provider_limits.get(
        "max_stream_json_record_bytes",
        MAX_STREAM_JSON_RECORD_BYTES,
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return MAX_STREAM_JSON_RECORD_BYTES
    if value < 1:
        return MAX_STREAM_JSON_RECORD_BYTES
    return value

ProcessRunner = Callable[[list[str], Path], Iterator[str]]
ProviderEventCallback = Callable[[dict[str, Any]], None]


def raise_for_cursor_cli_exit(
    return_code: int,
    *,
    status: dict[str, Any] | None,
    stderr: str = "",
) -> None:
    """Raise ``ProviderTurnError`` unless the janitor reported a successful turn."""

    detail = stderr.strip() or f"exit code {return_code}"
    if status is not None:
        drain = status.get("drain")
        if drain in {DrainResult.UNVERIFIABLE.value, DrainResult.SURVIVORS.value}:
            raise ProviderTurnCleanupError(f"Cursor CLI cleanup failed: {detail}")
        agent_code = status.get("agent_code", return_code)
        if agent_code in (None, 0):
            return
        if (
            isinstance(agent_code, int)
            and agent_code < 0
            and status.get("stop_requested") is True
            and drain == DrainResult.CLEAN.value
        ):
            return
        raise ProviderTurnError(f"Cursor CLI failed: {detail}")
    if return_code == 0:
        return
    raise ProviderTurnError(f"Cursor CLI failed: {detail}")


def janitor_group_was_cleaned(
    return_code: int,
    status: dict[str, Any] | None,
) -> bool:
    """Whether the owned process group was observed empty after this turn."""

    if status is not None:
        return status.get("drain") == DrainResult.CLEAN.value
    return return_code == 0


def _windows_pipe_has_data(fd: int, timeout: float | None, *, proc: subprocess.Popen[str]) -> bool:
    """Wait until a Windows pipe has bytes, the process exits, or *timeout* elapses."""

    try:
        import msvcrt
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False
    handle = msvcrt.get_osfhandle(fd)
    kernel32 = ctypes.windll.kernel32
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    peek.restype = wintypes.BOOL
    avail = wintypes.DWORD(0)
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    while True:
        if proc.poll() is not None:
            return True
        peeked = peek(handle, None, 0, None, ctypes.byref(avail), None)
        if not peeked:
            return False
        if int(avail.value) > 0:
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _stdout_fd_readable(
    fd: int,
    timeout: float | None,
    *,
    proc: subprocess.Popen[str],
) -> bool:
    if sys.platform == "win32":
        return _windows_pipe_has_data(fd, timeout, proc=proc)
    try:
        ready, _, _ = select.select([fd], [], [], None if timeout is None else max(0.0, timeout))
    except (OSError, ValueError):
        return True
    return bool(ready)


class _SubprocessStdoutIterator(Iterator[str]):
    """Eager-start subprocess runner so callers can track PID before first stdout line."""

    def __init__(
        self,
        argv: list[str],
        cwd: Path,
        *,
        env: Mapping[str, str] | None = None,
        active_proc: list[subprocess.Popen[str] | None] | None = None,
        ready_timeout: float | None = None,
        max_record_bytes: int | None = None,
    ) -> None:
        popen_kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if env is not None:
            popen_kwargs["env"] = dict(env)
        spawn_argv = list(argv)
        status_r: int | None = None
        status_w: int | None = None
        started_r: int | None = None
        started_w: int | None = None
        if sys.platform != "win32":
            from core_tools.provider.session_janitor import janitor_command

            status_r, status_w = os.pipe()
            started_r, started_w = os.pipe()
            popen_kwargs["start_new_session"] = True
            popen_kwargs["stdin"] = subprocess.PIPE
            popen_kwargs["pass_fds"] = (status_w, started_w)
            spawn_argv = janitor_command(
                argv,
                status_fd=status_w,
                started_fd=started_w,
                ready_timeout=(
                    DEFAULT_AGENT_START_TIMEOUT_SECONDS
                    if ready_timeout is None
                    else max(0.0, ready_timeout)
                ),
            )

        try:
            self._proc = subprocess.Popen(spawn_argv, **popen_kwargs)
        except OSError as exc:
            for fd in (status_r, status_w, started_r, started_w):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            raise ProviderTurnError(f"failed to start Cursor CLI: {exc}") from exc
        if popen_kwargs.get("start_new_session") is True and self._proc.pid:
            setattr(self._proc, "_core_tools_session_pgid", self._proc.pid)
        if status_w is not None:
            os.close(status_w)
        if started_w is not None:
            os.close(started_w)
        self._status_read_fd = status_r
        self._started_read_fd = started_r
        self._agent_started = started_r is None
        if self._proc is not None and status_r is not None:
            owner = JanitorStatusOwner(status_r)
            owner.bind(self._proc)
            setattr(self._proc, "_core_tools_janitor_status_owner", owner)

        if active_proc is not None:
            active_proc[0] = self._proc

        if self._proc.stdout is None:
            if active_proc is not None:
                active_proc[0] = None
            self.close()
            raise ProviderTurnError("Cursor CLI stdout pipe was not available")

        self._active_proc = active_proc
        self._stderr_tail = bytearray()
        self._stderr_truncated = False
        self._stderr_done = threading.Event()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._finished = False
        self._finalized = False
        self._stdout_buf = bytearray()
        self._stdout_eof = False
        try:
            configured = (
                MAX_STREAM_JSON_RECORD_BYTES
                if max_record_bytes is None
                else int(max_record_bytes)
            )
        except (TypeError, ValueError):
            configured = MAX_STREAM_JSON_RECORD_BYTES
        self._max_record_bytes = (
            configured if configured >= 1 else MAX_STREAM_JSON_RECORD_BYTES
        )
        self._leader_identity = (
            read_process_identity(self._proc.pid)
            if self._proc.pid is not None
            else None
        )

    def wait_agent_started(self, timeout: float | None = None) -> None:
        """Block until the janitor reports the real agent child was spawned."""

        fd = getattr(self, "_started_read_fd", None)
        if fd is None or getattr(self, "_agent_started", True):
            return
        budget = (
            DEFAULT_AGENT_START_TIMEOUT_SECONDS
            if timeout is None
            else max(0.0, timeout)
        )
        deadline = time.monotonic() + budget

        def _fail() -> None:
            self._close_started_fd()
            raise ProviderTurnStartupError("provider agent failed to start")

        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                _fail()
            pid = getattr(self._proc, "pid", None)
            if pid:
                state = inspect_pid_liveness(pid, timeout=min(0.05, remaining))
                if state is PidInspectState.GONE:
                    _fail()
            try:
                ready, _, _ = select.select([fd], [], [], min(0.05, remaining))
            except (OSError, ValueError):
                _fail()
            if not ready:
                continue
            try:
                data = os.read(fd, 8)
            except OSError:
                _fail()
            if not data:
                _fail()
            self._close_started_fd()
            self._agent_started = True
            return

    def _close_started_fd(self) -> None:
        fd = getattr(self, "_started_read_fd", None)
        self._started_read_fd = None
        if fd is None:
            return
        try:
            os.close(fd)
        except OSError:
            pass

    def _close_status_fd(self) -> None:
        self._status_read_fd = None
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        owner = getattr(proc, "_core_tools_janitor_status_owner", None)
        if owner is not None:
            owner.close()
            return
        fd = getattr(proc, "_core_tools_janitor_status_fd", None)
        if fd is None:
            return
        setattr(proc, "_core_tools_janitor_status_fd", None)
        try:
            os.close(fd)
        except OSError:
            pass

    def close(self) -> None:
        """Idempotently close status, stdio, and thread resources without waiting."""

        self._close_status_fd()
        self._close_started_fd()
        self._finished = True
        proc = getattr(self, "_proc", None)
        if proc is not None:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is None:
                    continue
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        thread = getattr(self, "_stderr_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.2)

    def __enter__(self) -> _SubprocessStdoutIterator:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self._close_status_fd()
        except Exception:
            return

    def _read_janitor_status(self) -> dict[str, Any] | None:
        proc = getattr(self, "_proc", None)
        if proc is None:
            return None
        return read_bound_janitor_status(proc, timeout=JANITOR_PARENT_WAIT_SECONDS)

    def _append_stderr_bytes(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._stderr_tail.extend(chunk)
        if len(self._stderr_tail) > _STDERR_TAIL_MAX_BYTES:
            self._stderr_truncated = True
            del self._stderr_tail[: len(self._stderr_tail) - _STDERR_TAIL_MAX_BYTES]

    def _drain_stderr(self) -> None:
        if self._proc.stderr is None:
            self._stderr_done.set()
            return
        try:
            while True:
                try:
                    chunk = self._proc.stderr.buffer.read(8192)
                except (OSError, ValueError):
                    break
                if not chunk:
                    break
                self._append_stderr_bytes(chunk)
        finally:
            self._stderr_done.set()

    def __iter__(self) -> _SubprocessStdoutIterator:
        return self

    def wait_readable(self, timeout: float) -> bool:
        """Return True when a complete stdout line is buffered or the process exited."""

        return self._wait_for_complete_line(timeout)

    def _pop_complete_line(self) -> str | None:
        idx = self._stdout_buf.find(b"\n")
        if idx < 0:
            return None
        assembled = idx + 1
        if assembled > self._max_record_bytes:
            self._abandon_stdout_after_record_cap()
            raise ProviderStreamRecordTooLargeError(
                f"stream-json record exceeded {self._max_record_bytes} bytes"
            )
        raw = bytes(self._stdout_buf[:idx])
        del self._stdout_buf[: idx + 1]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        return raw.decode("utf-8", errors="replace")

    def _stdout_fd(self) -> int | None:
        stdout = self._proc.stdout
        if stdout is None:
            return None
        try:
            return stdout.fileno()
        except (OSError, ValueError):
            return None

    def _fill_stdout_buffer(self, timeout: float | None) -> bool:
        """Read available bytes into the line buffer. True if data, EOF, or exit."""

        if self._stdout_eof or self._finished:
            return True
        fd = self._stdout_fd()
        if fd is None:
            self._stdout_eof = True
            return True
        if not _stdout_fd_readable(fd, timeout, proc=self._proc):
            return False
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            return False
        except (OSError, ValueError):
            self._stdout_eof = True
            return True
        if not chunk:
            self._stdout_eof = True
            return True
        self._stdout_buf.extend(chunk)
        return True

    def _incomplete_tail_start(self) -> int:
        last_newline = self._stdout_buf.rfind(b"\n")
        return 0 if last_newline < 0 else last_newline + 1

    def _incomplete_tail_over_cap(self) -> bool:
        """True when the record after the last complete line is already too large."""

        start = self._incomplete_tail_start()
        return (len(self._stdout_buf) - start) >= self._max_record_bytes

    def _writer_still_live(self) -> bool:
        proc = getattr(self, "_proc", None)
        if proc is None or proc.pid is None:
            return False
        raw_poll = getattr(proc, "_core_tools_raw_poll", None)
        if callable(raw_poll):
            try:
                if raw_poll() is not None:
                    return False
            except Exception:
                pass
        return is_pid_alive(proc.pid)

    def _reap_writer_if_exited(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        raw_wait = getattr(proc, "_core_tools_raw_wait", None)
        if not callable(raw_wait):
            return
        try:
            raw_wait(timeout=0)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _abandon_stdout_after_record_cap(self) -> None:
        """Stop reading and terminate a still-owned live writer, never a stale PGID."""

        self._stdout_eof = True
        stdout = getattr(self._proc, "stdout", None)
        if stdout is not None:
            try:
                stdout.close()
            except (OSError, ValueError):
                pass
        proc = getattr(self, "_proc", None)
        if proc is None or sys.platform == "win32":
            return
        if not self._writer_still_live():
            self._reap_writer_if_exited()
            return
        identity = self._leader_identity
        if identity is None or identity.pid != proc.pid:
            identity = read_process_identity(proc.pid, timeout=0.05)
        if identity is None:
            self._reap_writer_if_exited()
            return
        if inspect_process_identity(identity, timeout=0.05) is not (
            IdentityInspectState.LIVE_MATCH
        ):
            self._reap_writer_if_exited()
            return
        live_pgid = read_process_group_id(identity.pid, timeout=0.05)
        cached_pgid = getattr(proc, "_core_tools_session_pgid", None)
        if live_pgid is None or live_pgid <= 0:
            self._reap_writer_if_exited()
            return
        if isinstance(cached_pgid, int) and cached_pgid > 0 and live_pgid != cached_pgid:
            return
        terminate_verified_process_identity(
            identity,
            proc=proc,
            pgid=live_pgid,
            timeout=0.35,
        )
        if self._writer_still_live() and inspect_process_identity(
            identity, timeout=0.05
        ) is IdentityInspectState.LIVE_MATCH:
            follow_pgid = read_process_group_id(identity.pid, timeout=0.05)
            if (
                follow_pgid is not None
                and follow_pgid > 0
                and follow_pgid == live_pgid
            ):
                try:
                    os.killpg(follow_pgid, signal.SIGKILL)
                except OSError:
                    pass
        self._reap_writer_if_exited()

    def _raise_if_current_record_too_large(self) -> None:
        """Refuse the record currently being assembled if it exceeds the cap.

        Complete records still waiting at the front of the buffer are checked
        when they are popped. The cap includes the terminating newline; an
        incomplete tail that has already reached the cap is too large.
        """

        if self._incomplete_tail_over_cap():
            self._abandon_stdout_after_record_cap()
            raise ProviderStreamRecordTooLargeError(
                f"stream-json record exceeded {self._max_record_bytes} bytes"
            )

    def _finish_unterminated_record(self) -> None:
        if self._stdout_buf and b"\n" not in self._stdout_buf:
            self._stdout_buf.extend(b"\n")
        self._raise_if_current_record_too_large()

    def _drain_stdout_to_eof(self) -> None:
        fd = self._stdout_fd()
        if fd is None:
            self._stdout_eof = True
            return
        restore_flags: int | None = None
        if sys.platform != "win32":
            import fcntl

            try:
                restore_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, restore_flags & ~os.O_NONBLOCK)
            except OSError:
                restore_flags = None
        try:
            while True:
                if self._incomplete_tail_over_cap():
                    self._abandon_stdout_after_record_cap()
                    return
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    if self._proc.poll() is None:
                        return
                    time.sleep(0.001)
                    continue
                except (OSError, ValueError):
                    self._stdout_eof = True
                    return
                if not chunk:
                    self._stdout_eof = True
                    return
                self._stdout_buf.extend(chunk)
        finally:
            if restore_flags is not None:
                import fcntl

                try:
                    fcntl.fcntl(fd, fcntl.F_SETFL, restore_flags)
                except OSError:
                    pass

    def _wait_for_complete_line(self, timeout: float | None) -> bool:
        if self._finished:
            return True
        if b"\n" in self._stdout_buf:
            return True
        self._raise_if_current_record_too_large()
        if self._stdout_eof:
            self._finish_unterminated_record()
            return True
        if self._proc.poll() is not None:
            self._drain_stdout_to_eof()
            if b"\n" in self._stdout_buf:
                return True
            self._finish_unterminated_record()
            return bool(self._stdout_buf) or self._stdout_eof
        idle_window = None if timeout is None else max(0.0, timeout)
        idle_deadline = None if idle_window is None else time.monotonic() + idle_window
        while True:
            if b"\n" in self._stdout_buf:
                return True
            self._raise_if_current_record_too_large()
            remaining = (
                None if idle_deadline is None else max(0.0, idle_deadline - time.monotonic())
            )
            before = len(self._stdout_buf)
            got = self._fill_stdout_buffer(remaining)
            if got:
                if b"\n" in self._stdout_buf:
                    return True
                self._raise_if_current_record_too_large()
                if self._proc.poll() is not None and not self._stdout_eof:
                    self._drain_stdout_to_eof()
                if self._stdout_eof or self._proc.poll() is not None:
                    if b"\n" in self._stdout_buf:
                        return True
                    self._finish_unterminated_record()
                    return True
                if (
                    idle_deadline is not None
                    and idle_window is not None
                    and len(self._stdout_buf) > before
                ):
                    idle_deadline = time.monotonic() + idle_window
                continue
            if idle_deadline is None:
                continue
            if remaining <= 0:
                self._raise_if_current_record_too_large()
                return False

    def __next__(self) -> str:
        if self._finished:
            raise StopIteration
        while True:
            line = self._pop_complete_line()
            if line is not None:
                stripped = line.strip()
                if stripped:
                    return stripped
                continue
            self._raise_if_current_record_too_large()
            if self._stdout_eof or self._finished:
                self._finalize()
                raise StopIteration
            if not self._wait_for_complete_line(None):
                self._finalize()
                raise StopIteration
            if not self._stdout_buf and (self._stdout_eof or self._proc.poll() is not None):
                self._finalize()
                raise StopIteration

    def read_nonempty_line(self, timeout: float) -> str | None:
        """Return the next non-empty line, or None when idle *timeout* elapses."""

        if self._finished:
            raise StopIteration
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if not self._wait_for_complete_line(remaining):
                return None
            line = self._pop_complete_line()
            if line is None:
                self._raise_if_current_record_too_large()
                if self._stdout_eof:
                    self._finalize()
                    raise StopIteration
                if self._finished:
                    raise StopIteration
                continue
            stripped = line.strip()
            if stripped:
                return stripped

    def _finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            self._stderr_done.wait(timeout=5)
            stderr = self._stderr_tail.decode("utf-8", errors="replace")
            if self._stderr_truncated:
                stderr = (
                    f"[stderr truncated; showing last {_STDERR_TAIL_MAX_BYTES} bytes]\n"
                    f"{stderr}"
                )
            status = self._read_janitor_status()
            try:
                return_code = self._proc.wait()
            except subprocess.TimeoutExpired:
                return_code = (
                    self._proc.returncode
                    if self._proc.returncode is not None
                    else -1
                )
            setattr(self._proc, "_core_tools_janitor_status", status)
            raise_for_cursor_cli_exit(return_code, status=status, stderr=stderr)
        finally:
            self.close()


def default_process_runner(
    argv: list[str],
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
    active_proc: list[subprocess.Popen[str] | None] | None = None,
    max_record_bytes: int | None = None,
) -> Iterator[str]:
    """Run the Cursor CLI and yield stdout lines."""

    return _SubprocessStdoutIterator(
        argv,
        cwd,
        env=env,
        active_proc=active_proc,
        max_record_bytes=max_record_bytes,
    )


def resolve_agent_binary(configured: str | None) -> str:
    """Resolve the Cursor agent binary from config or PATH."""

    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise ProviderBinaryNotFoundError(
            f"configured provider binary not found: {configured}"
        )

    for name in ("agent", "cursor-agent"):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    raise ProviderBinaryNotFoundError(
        "Cursor CLI not found on PATH (expected `agent` or `cursor-agent`). "
        "Install: curl https://cursor.com/install -fsS | bash"
    )


def resolve_provider_cli_model(*, model: str | None = None) -> str | None:
    """Normalize a configured model value for provider CLI argv."""

    if model is None:
        return None
    resolved = str(model).strip()
    if not resolved or resolved.lower() == "auto":
        return None
    return resolved


def format_provider_model_name(model: str | None) -> str:
    """Return the session lifecycle label for a provider-resolved model."""

    resolved = resolve_provider_cli_model(model=model)
    if resolved is None:
        return "auto"
    return resolved


def enrich_provider_observability_event(
    event: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    """Attach session identity to a normalized provider stream event."""

    enriched = dict(event)
    enriched["session_id"] = session_id
    return enriched


def build_agent_argv(
    config: dict[str, Any],
    *,
    binary: str,
    workspace: Path,
    session_id: str | None = None,
    prompt: str | None = None,
    model: str | None = None,
) -> list[str]:
    """Construct a Cursor CLI argv for a non-interactive streamed turn."""

    # --force is required for non-interactive turns: without it, shell/tool
    # calls are rejected and the planner/producer cannot drive `tdp agent …`.
    argv: list[str] = [
        binary,
        "--print",
        "--output-format",
        "stream-json",
        "--trust",
        "--approve-mcps",
        "--force",
        "--workspace",
        str(workspace),
    ]

    resolved_model = resolve_provider_cli_model(model=model)
    if resolved_model:
        argv.extend(["--model", resolved_model])

    if session_id and not str(session_id).startswith(_CURSOR_TRANSIENT_SESSION_PREFIX):
        argv.extend(["--resume", session_id])

    if prompt:
        argv.append(prompt)

    return argv


@dataclass
class _CursorSession:
    role: str
    kind: str
    manifest: dict[str, Any]
    model: str | None
    pending_events: deque[dict[str, Any]] = field(default_factory=deque)
    pending_argv: list[str] | None = None
    turn_queued: bool = False
    turn_running: bool = False
    turn_complete: bool = False
    turn_aborted: bool = False
    turn_error: ProviderError | None = None
    turn_remote_observed: bool = False
    collector_thread: threading.Thread | None = None
    pinned_durable_id: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    condition: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        self.condition = threading.Condition(self.lock)


@dataclass(frozen=True)
class _SessionSurvival:
    pids: tuple[int, ...] = ()
    unresolved: bool = False

    def __iter__(self):
        return iter(self.pids)

    def __contains__(self, item: object) -> bool:
        return item in self.pids

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _SessionSurvival):
            return self.pids == other.pids and self.unresolved == other.unresolved
        if isinstance(other, tuple):
            return self.pids == other
        return NotImplemented


@dataclass
class _TrackedTurnProc:
    session_id: str
    role: str
    proc: subprocess.Popen[str] | None = None
    identity: ProcessIdentity | None = None
    pgid: int | None = None
    member_identities: tuple[ProcessIdentity, ...] | None = None
    group_observed_gone: bool = False
    generation: int = 0
    owner_id: str | None = None


class CursorProvider:
    """Cursor CLI adapter with injectable process runner for tests."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        workspace: Path | None = None,
        runner: ProcessRunner | None = None,
        binary: str | None = None,
        skip_probe: bool = False,
        extra_env: Mapping[str, str] | None = None,
        on_provider_event: ProviderEventCallback | None = None,
    ) -> None:
        if sys.platform == "win32":
            raise ProviderUnsupportedPlatformError(
                "CursorProvider is POSIX-only; Windows process-tree ownership "
                "is not supported"
            )
        self._config = config
        provider_cfg = config.get("provider") or {}
        self._workspace = Path(workspace or Path.cwd()).resolve()
        self._extra_env = dict(extra_env or {})
        self._subprocess_env = self._build_subprocess_env(self._extra_env)
        base_runner = runner or default_process_runner
        self._runner = self._wrap_runner(base_runner)
        self._skip_probe = bool(skip_probe or provider_cfg.get("skip_probe"))
        configured_binary = binary or provider_cfg.get("binary")
        self._binary = resolve_agent_binary(
            str(configured_binary) if configured_binary else None
        )
        if not self._skip_probe:
            self._probe_binary()
        self._sessions: dict[str, _CursorSession] = {}
        self._session_aliases: dict[str, str] = {}
        self._pending_counter = 0
        self._session_registry_lock = threading.RLock()
        self._turn_proc_lock = threading.Lock()
        self._tracked_turn_procs: dict[int, _TrackedTurnProc] = {}
        self._collect_context = threading.local()
        self._on_provider_event = on_provider_event
        self._shutting_down = False
        self._enrich_threads_lock = threading.Lock()
        self._enrich_threads: dict[str, list[threading.Thread]] = {}

    def start_primary_session(
        self,
        role: str,
        context_manifest: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        return self._register_session(
            role=role,
            kind="primary",
            manifest=context_manifest,
            prompt=format_manifest_prompt(role, context_manifest),
            model=model,
            resume_session_id=None,
        )

    def resume_primary_session(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        role: str,
        model: str | None = None,
    ) -> None:
        canonical_id = self._ensure_durable_session(
            session_id,
            role=role,
            kind="primary",
            model=model,
        )
        self._queue_turn(
            canonical_id,
            prompt=format_request_prompt(request),
        )

    def start_reviewer_session(
        self,
        review_package: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        return self._register_session(
            role="reviewer",
            kind="reviewer",
            manifest=review_package,
            prompt=format_request_prompt(review_package),
            model=model,
            resume_session_id=None,
        )

    def send(self, session_id: str, request: dict[str, Any], *, model: str | None = None) -> None:
        canonical_id = self.canonical_session_id(session_id)
        existing = self._sessions.get(canonical_id)
        if existing is not None and (
            existing.kind != "reviewer" or existing.role != "reviewer"
        ):
            raise ProviderSessionError(
                (
                    f"send() is only supported for reviewer sessions; "
                    f"session {canonical_id} is {existing.role}/{existing.kind}"
                ),
                session_id=canonical_id,
            )
        canonical_id = self._ensure_durable_session(
            session_id,
            role="reviewer",
            kind="reviewer",
            model=model,
        )
        self._queue_turn(
            canonical_id,
            prompt=format_request_prompt(request),
        )

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        canonical_id = self.canonical_session_id(session_id)
        session = self._require_session(canonical_id)
        self._ensure_turn_started(canonical_id, session)
        while True:
            event = None
            turn_error = None
            complete = False
            with session.condition:
                while not session.pending_events and not session.turn_complete:
                    session.condition.wait(timeout=0.05)
                if session.pending_events:
                    event = session.pending_events.popleft()
                elif session.turn_complete:
                    turn_error = session.turn_error
                    complete = True
            if event is not None:
                yield event
                continue
            if complete:
                if turn_error is not None:
                    raise turn_error
                break

    def canonical_session_id(self, session_id: str) -> str:
        with self._session_registry_lock:
            seen: set[str] = set()
            current = session_id
            while True:
                nxt = self._session_aliases.get(current)
                if nxt is None or nxt == current:
                    return current
                if current in seen:
                    return current
                seen.add(current)
                current = nxt

    def get_capabilities(self) -> dict[str, Any]:
        models: list[str] = []
        for line in self._runner([self._binary, "models"], self._workspace):
            stripped = line.strip()
            if not stripped or stripped.startswith("Available models"):
                continue
            model_id = stripped.split(" - ", 1)[0].strip()
            if model_id:
                models.append(model_id)

        provider_cfg = self._config.get("provider") or {}
        return {
            "provider": "cursor",
            "binary": self._binary,
            "workspace": str(self._workspace),
            "models": models,
            "features": {"resume": True, "stream_json": True},
        }

    def get_session_reference(self, session_id: str) -> dict[str, Any]:
        canonical_id = self.canonical_session_id(session_id)
        session = self._require_session(canonical_id)
        return {
            "provider": "cursor",
            "session_id": canonical_id,
            "role": session.role,
            "kind": session.kind,
            "model": format_provider_model_name(session.model),
            "binary": self._binary,
            "workspace": str(self._workspace),
        }

    def list_active_sessions(self) -> list[dict[str, str]]:
        with self._session_registry_lock:
            return [
                {
                    "session_id": session_id,
                    "role": session.role,
                    "kind": session.kind,
                    "model": format_provider_model_name(session.model),
                }
                for session_id, session in self._sessions.items()
            ]

    def reconcile_terminated_pids(self, terminated_pids: list[int]) -> None:
        """Drop tracked PIDs and sessions confirmed terminated externally."""

        confirmed_dead = {
            int(pid) for pid in terminated_pids if isinstance(pid, int)
        }
        if confirmed_dead:
            with self._turn_proc_lock:
                for pid in confirmed_dead:
                    entry = self._tracked_turn_procs.get(pid)
                    if entry is None:
                        continue
                    if not self._tracked_tree_is_live(entry):
                        self._tracked_turn_procs.pop(pid, None)
        with self._session_registry_lock:
            for session_id in list(self._sessions.keys()):
                self._prune_dead_tracked_pids_for_session(session_id)
                if not self._session_has_surviving_pids(session_id):
                    self._remove_session(session_id)

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("terminate_session timeout must be positive")
        canonical_id = self.canonical_session_id(session_id)
        deadline = time.monotonic() + timeout
        abort_budget = min(timeout, timeout / 2.0)
        try:
            self.abort_turn(canonical_id, timeout=abort_budget)
        except ProviderLifecycleTimeoutError as exc:
            raise ProviderSessionTerminationError(
                (
                    f"failed to terminate provider session {canonical_id}: "
                    f"{exc}"
                ),
                session_id=canonical_id,
                surviving_pids=exc.surviving_pids,
            ) from exc
        remaining = max(0.0, deadline - time.monotonic())
        try:
            self.wait_turn_settled(canonical_id, timeout=remaining)
        except ProviderTurnError as exc:
            raise ProviderLifecycleTimeoutError(
                str(exc),
                session_id=canonical_id,
            ) from exc
        remaining = max(0.0, deadline - time.monotonic())
        records = self._terminate_tracked_turn_procs_for_session(
            canonical_id,
            timeout=remaining,
        )
        remaining = max(0.0, deadline - time.monotonic())
        survival = self._surviving_pids_for_session(
            canonical_id, records, timeout=remaining
        )
        if survival.pids:
            raise ProviderSessionTerminationError(
                (
                    f"failed to terminate provider session {canonical_id}: "
                    f"surviving agent processes {list(survival.pids)}"
                ),
                session_id=canonical_id,
                surviving_pids=survival.pids,
            )
        if survival.unresolved:
            raise ProviderSessionTerminationError(
                (
                    f"failed to terminate provider session {canonical_id}: "
                    "unresolved provider process ownership"
                ),
                session_id=canonical_id,
                surviving_pids=(),
            )
        remaining = max(0.0, deadline - time.monotonic())
        self._prune_dead_tracked_pids_for_session(canonical_id, timeout=remaining)
        remaining = max(0.0, deadline - time.monotonic())
        if self._session_has_surviving_pids(canonical_id, timeout=remaining):
            raise ProviderSessionTerminationError(
                (
                    f"failed to terminate provider session {canonical_id}: "
                    "unresolved provider process ownership"
                ),
                session_id=canonical_id,
                surviving_pids=(),
            )
        with self._session_registry_lock:
            self._remove_session(canonical_id)

    def abort_turn(self, session_id: str, *, timeout: float = 2.0) -> None:
        """End the current in-flight turn without dropping the durable session.

        Marks the turn aborted and wakes ``stream_events`` waiters. Callers that
        need the collector thread to finish must invoke ``wait_turn_settled`` after
        draining or closing the turn. *timeout* bounds any wait for tracked
        process teardown associated with the abort.
        """

        if timeout <= 0:
            raise ValueError("abort_turn timeout must be positive")
        deadline = time.monotonic() + timeout
        canonical_id = self.canonical_session_id(session_id)
        with self._session_registry_lock:
            session = self._sessions.get(canonical_id)
        if session is None:
            return
        with session.condition:
            session.pending_events.clear()
            session.pending_argv = None
            session.turn_queued = False
            session.turn_aborted = True
        self._abort_session_turn(session, error=None)
        remaining = max(0.0, deadline - time.monotonic())
        self._wait_turn_enrichment(timeout=remaining, session_id=canonical_id)
        remaining = max(0.0, deadline - time.monotonic())
        records = self._terminate_tracked_turn_procs_for_session(
            canonical_id,
            timeout=remaining,
        )
        remaining = max(0.0, deadline - time.monotonic())
        self._prune_dead_tracked_pids_for_session(canonical_id, timeout=remaining)
        remaining = max(0.0, deadline - time.monotonic())
        survival = self._surviving_pids_for_session(
            canonical_id, records, timeout=remaining
        )
        if survival.pids:
            raise ProviderLifecycleTimeoutError(
                (
                    f"abort_turn exceeded {timeout:g}s with surviving agent "
                    f"processes {list(survival.pids)}"
                ),
                session_id=canonical_id,
                surviving_pids=survival.pids,
            )
        if survival.unresolved:
            raise ProviderLifecycleTimeoutError(
                (
                    f"abort_turn exceeded {timeout:g}s: "
                    "unresolved provider process ownership"
                ),
                session_id=canonical_id,
            )

    def terminate_all_sessions(self) -> list[dict[str, Any]]:
        """Stop in-flight turns and drop tracked provider sessions."""

        self._shutting_down = True
        try:
            terminated: list[dict[str, Any]] = []
            self._abort_inflight_sessions()
            self._wait_turn_enrichment(timeout=DEFAULT_TURN_TREE_CLEANUP_SECONDS)
            terminated.extend(self._terminate_tracked_turn_procs())

            with self._session_registry_lock:
                session_snapshot = list(self._sessions.values())
                session_ids = list(self._sessions.keys())
            for session in session_snapshot:
                thread = session.collector_thread
                if thread is not None and thread.is_alive():
                    thread.join(timeout=0.5)

            terminated.extend(self._terminate_tracked_turn_procs())

            for session_id in session_ids:
                if not self._session_has_surviving_pids(session_id):
                    self._prune_dead_tracked_pids_for_session(session_id)
                    if not self._session_has_surviving_pids(session_id):
                        with self._session_registry_lock:
                            self._remove_session(session_id)

            return terminated
        finally:
            self._shutting_down = False

    def _terminate_tracked_turn_procs(
        self,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        terminated: list[dict[str, Any]] = []
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._turn_proc_lock:
            tracked = dict(self._tracked_turn_procs)

        tracked_ids = (
            self._tracked_session_ids(session_id) if session_id is not None else None
        )
        seen_pids: set[int] = set()
        for pid, entry in tracked.items():
            if tracked_ids is not None and entry.session_id not in tracked_ids:
                continue
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            self._refresh_tracked_members(entry, timeout=remaining)
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            record = self._termination_record_for_tracked_proc(entry)
            result = terminate_verified_process_identity(
                entry.identity,
                proc=entry.proc,
                pgid=entry.pgid,
                member_identities=(
                    list(entry.member_identities)
                    if entry.member_identities is not None
                    else None
                ),
                timeout=remaining,
            )
            if result == TerminateIdentityResult.TERMINATED:
                terminated.append({**record, "reason": "terminated"})
                self._unregister_tracked_turn_proc_by_pid(pid)
            elif result is TerminateIdentityResult.IDENTITY_MISMATCH:
                self._unregister_tracked_turn_proc_by_pid(pid)
            elif result is TerminateIdentityResult.ALREADY_GONE:
                if not self._tracked_tree_is_live(entry, timeout=remaining):
                    terminated.append({**record, "reason": "terminated"})
                    self._unregister_tracked_turn_proc_by_pid(pid)
            elif result == TerminateIdentityResult.FAILED:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if self._failed_tracking_is_stale(entry, timeout=remaining):
                    terminated.append(
                        {
                            **record,
                            "reason": "stale_reconciled",
                            "tree_status": "stale_reconciled",
                            "group_observed_gone": True,
                        }
                    )
                    self._unregister_tracked_turn_proc_by_pid(pid)
                else:
                    terminated.append(
                        {
                            **record,
                            "reason": "termination_failed",
                            "tree_status": "unresolved",
                            "group_observed_gone": bool(entry.group_observed_gone),
                        }
                    )
        return terminated

    @staticmethod
    def _termination_record_for_tracked_proc(
        entry: _TrackedTurnProc,
    ) -> dict[str, Any]:
        pid = entry.proc.pid if entry.proc is not None else (
            entry.identity.pid if entry.identity is not None else 0
        )
        record: dict[str, Any] = {
            "pid": pid,
            "role": entry.role,
            "session_id": entry.session_id,
        }
        if entry.pgid is not None:
            record["pgid"] = entry.pgid
        members = list(entry.member_identities or ())
        if entry.identity is not None and entry.identity not in members:
            members = [entry.identity, *members]
        if members:
            record["member_pids"] = [identity.pid for identity in members]
            record["member_identities"] = [
                process_identity_token(identity) for identity in members
            ]
        if entry.identity is not None:
            record["start_time"] = entry.identity.start_time
            record["process_identity"] = process_identity_token(entry.identity)
            record["run_id"] = entry.identity.run_id
        owner_id = entry.owner_id
        if owner_id is None and entry.identity is not None:
            owner_id = entry.identity.owner_id
        if owner_id:
            record["provider_owner_id"] = owner_id
        return record

    def _terminate_tracked_turn_procs_for_session(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        return self._terminate_tracked_turn_procs(session_id=session_id, timeout=timeout)

    def _abort_session_turn(
        self,
        session: _CursorSession,
        *,
        error: ProviderTurnError | None,
    ) -> None:
        with session.condition:
            session.turn_running = False
            session.turn_complete = True
            session.pending_argv = None
            session.turn_queued = False
            if error is not None:
                session.turn_error = error
            session.condition.notify_all()

    def _abort_inflight_sessions(self) -> None:
        with self._session_registry_lock:
            inflight = list(self._sessions.items())
        for session_id, session in inflight:
            self._abort_session_turn(
                session,
                error=ProviderTurnError(
                    "provider session terminated",
                    session_id=session_id,
                ),
            )

    def set_capability_token(
        self,
        _token: str | None,
        *,
        token_file: str | None = None,
    ) -> None:
        if token_file:
            self._extra_env["TDP_CAPABILITY_TOKEN_FILE"] = token_file
        else:
            self._extra_env.pop("TDP_CAPABILITY_TOKEN_FILE", None)
        self._subprocess_env = self._build_subprocess_env(self._extra_env)

    def _probe_binary(self) -> None:
        run_kwargs: dict[str, Any] = {
            "cwd": str(self._workspace),
            "capture_output": True,
            "text": True,
            "check": False,
        }
        if self._subprocess_env is not None:
            run_kwargs["env"] = self._subprocess_env
        try:
            proc = subprocess.run(
                [self._binary, "--version"],
                **run_kwargs,
            )
        except OSError as exc:
            raise ProviderBinaryNotFoundError(
                f"failed to execute Cursor CLI binary {self._binary}: {exc}"
            ) from exc
        if proc.returncode != 0:
            raise ProviderBinaryNotFoundError(
                f"Cursor CLI probe failed for {self._binary}: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )

    def _require_session(self, session_id: str) -> _CursorSession:
        canonical_id = self.canonical_session_id(session_id)
        with self._session_registry_lock:
            session = self._sessions.get(canonical_id)
        if session is None:
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )
        return session

    def _ensure_durable_session(
        self,
        session_id: str,
        *,
        role: str,
        kind: str,
        model: str | None = None,
    ) -> str:
        """Re-register a persisted Cursor session after in-memory teardown."""

        canonical_id = self.canonical_session_id(session_id)
        with self._session_registry_lock:
            if canonical_id in self._sessions:
                existing = self._sessions[canonical_id]
                if existing.role != role or existing.kind != kind:
                    raise ProviderSessionError(
                        (
                            f"durable session {session_id} role/kind mismatch: "
                            f"existing role={existing.role!r} kind={existing.kind!r}, "
                            f"requested role={role!r} kind={kind!r}"
                        ),
                        session_id=session_id,
                    )
                return canonical_id
            if canonical_id.startswith(_CURSOR_TRANSIENT_SESSION_PREFIX):
                raise ProviderSessionError(
                    f"unknown provider session: {session_id}",
                    session_id=session_id,
                )
            session_model = resolve_provider_cli_model(model=model)
            self._sessions[canonical_id] = _CursorSession(
                role=role,
                kind=kind,
                manifest={},
                model=session_model,
            )
            return canonical_id

    def _new_pending_session_id(self) -> str:
        self._pending_counter += 1
        return f"{_CURSOR_TRANSIENT_SESSION_PREFIX}{self._pending_counter}"

    def _register_session(
        self,
        *,
        role: str,
        kind: str,
        manifest: dict[str, Any],
        prompt: str,
        model: str | None,
        resume_session_id: str | None,
    ) -> str:
        session_model = resolve_provider_cli_model(model=model)
        argv = build_agent_argv(
            self._config,
            binary=self._binary,
            workspace=self._workspace,
            session_id=resume_session_id,
            prompt=prompt,
            model=session_model,
        )
        with self._session_registry_lock:
            if resume_session_id is not None:
                session_id = resume_session_id
            else:
                self._pending_counter += 1
                session_id = f"{_CURSOR_TRANSIENT_SESSION_PREFIX}{self._pending_counter}"
            self._sessions[session_id] = _CursorSession(
                role=role,
                kind=kind,
                manifest=dict(manifest),
                model=session_model,
                pending_argv=argv,
                turn_queued=True,
            )
        return session_id

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        """Block until the in-flight collector thread for this session has finished."""

        canonical_id = self.canonical_session_id(session_id)
        with self._session_registry_lock:
            session = self._sessions.get(canonical_id)
        if session is None:
            return

        deadline = time.monotonic() + timeout
        with session.condition:
            while session.turn_running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderTurnError(
                        "timed out waiting for provider turn to settle for session "
                        f"{canonical_id}",
                        session_id=canonical_id,
                    )
                session.condition.wait(timeout=min(remaining, 0.05))
            thread = session.collector_thread

        if thread is not None and thread.is_alive():
            remaining = deadline - time.monotonic()
            if remaining > 0:
                thread.join(timeout=remaining)
            if thread.is_alive():
                raise ProviderTurnError(
                    "timed out waiting for provider collector to finish for session "
                    f"{canonical_id}",
                    session_id=canonical_id,
                )
        remaining = max(0.0, deadline - time.monotonic())
        self._wait_turn_enrichment(timeout=remaining, session_id=canonical_id)

    def _queue_turn(self, session_id: str, *, prompt: str) -> None:
        session = self._require_session(session_id)
        self.wait_turn_settled(session_id)
        argv = build_agent_argv(
            self._config,
            binary=self._binary,
            workspace=self._workspace,
            session_id=session_id,
            prompt=prompt,
            model=session.model,
        )
        with session.condition:
            if session.turn_running:
                raise ProviderTurnError(
                    f"provider turn already in progress for session {session_id}",
                    session_id=session_id,
                )
            if session.turn_queued:
                raise ProviderTurnError(
                    f"provider turn already queued for session {session_id}",
                    session_id=session_id,
                )
            session.pending_events.clear()
            session.pending_argv = argv
            session.turn_queued = True
            session.turn_running = False
            session.turn_complete = False
            session.turn_aborted = False
            session.turn_error = None
            session.collector_thread = None

    def _ensure_turn_started(self, session_id: str, session: _CursorSession) -> None:
        with session.condition:
            if session.turn_running or session.turn_complete:
                return
            if session.pending_argv is None:
                return
            argv = session.pending_argv
            session.pending_argv = None
            session.turn_queued = False
            session.turn_running = True
            thread = threading.Thread(
                target=self._collect_turn,
                args=(session_id, session, argv),
                daemon=True,
            )
            session.collector_thread = thread
            thread.start()

    def _collect_turn(
        self,
        session_id: str,
        session: _CursorSession,
        argv: list[str],
    ) -> None:
        try:
            self._collect_turn_once(session_id, session, argv)
        except ProviderSessionNotFoundError as exc:
            with session.condition:
                session.turn_error = exc
        except ProviderTurnStalledError as exc:
            with session.condition:
                if session.turn_aborted:
                    return
                session.turn_error = exc
        except ProviderTurnCleanupError as exc:
            with session.condition:
                if session.turn_aborted:
                    return
                session.turn_error = exc
        except ProviderSessionMismatchError as exc:
            with session.condition:
                if session.turn_aborted:
                    return
                session.turn_error = exc
        except ProviderSessionError as exc:
            with session.condition:
                if session.turn_aborted:
                    return
                session.turn_error = exc
        except ProviderTurnError as exc:
            with session.condition:
                if session.turn_aborted:
                    return
                session.turn_error = reclassify_provider_turn_error(
                    exc,
                    session_id=session_id,
                )
        finally:
            with session.condition:
                session.turn_running = False
                session.turn_complete = True
                session.condition.notify_all()

    def _session_turn_aborted(self, session: _CursorSession) -> bool:
        if self._shutting_down:
            return True
        with session.condition:
            if session.turn_aborted:
                return True
            error = session.turn_error
            if error is None:
                return False
            message = str(error).lower()
            return "terminated" in message or "shutting down" in message

    def _collect_turn_once(
        self,
        session_id: str,
        session: _CursorSession,
        argv: list[str],
    ) -> None:
        max_retries = self._max_retries_per_call()
        last_error: ProviderTurnError | None = None
        for attempt in range(max_retries + 1):
            if self._session_turn_aborted(session):
                raise ProviderTurnError(
                    "provider session terminated",
                    session_id=session_id,
                )
            try:
                session.turn_remote_observed = False
                self._collect_turn_stream(session_id, session, argv)
                return
            except ProviderSessionError:
                raise
            except ProviderTurnError as exc:
                if isinstance(
                    exc,
                    (
                        ProviderTurnStalledError,
                        ProviderTurnStartupError,
                        ProviderTurnCleanupError,
                        ProviderStreamRecordTooLargeError,
                    ),
                ):
                    raise exc
                classified = reclassify_provider_turn_error(exc, session_id=session_id)
                if isinstance(classified, ProviderSessionNotFoundError):
                    raise classified from exc
                if isinstance(classified, ProviderTurnCleanupError):
                    raise classified from exc
                if self._session_turn_aborted(session):
                    raise ProviderTurnError(
                        "provider session terminated",
                        session_id=session_id,
                    ) from exc
                if session.turn_remote_observed:
                    raise classified from exc
                last_error = classified
                if attempt < max_retries:
                    self._emit_provider_event(
                        enrich_provider_observability_event(
                            {
                                "type": "retry",
                                "text": str(exc),
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                            },
                            session_id=session_id,
                        )
                    )
                if attempt >= max_retries:
                    raise
        if last_error is not None:
            raise last_error

    def _collect_turn_stream(
        self,
        session_id: str,
        session: _CursorSession,
        argv: list[str],
    ) -> None:
        provider_session_id: str | None = None
        expected_durable_id: str | None = session.pinned_durable_id
        if expected_durable_id is None and not session_id.startswith(
            _CURSOR_TRANSIENT_SESSION_PREFIX
        ):
            expected_durable_id = session_id
        self._set_collect_context(session_id, session.role)
        try:
            try:
                stream = self._runner(argv, self._workspace)
            except ProviderTurnError as exc:
                classified = reclassify_provider_turn_error(exc, session_id=session_id)
                if isinstance(classified, ProviderSessionNotFoundError):
                    raise classified from exc
                raise

            for line in stream:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProviderTurnError(
                        f"invalid stream-json line from Cursor CLI: {line!r}"
                    ) from exc
                if not isinstance(raw, dict):
                    continue
                session_id, observed_id = self._observe_stream_session_identity(
                    session,
                    session_id,
                    expected_durable_id,
                    raw,
                )
                if observed_id is not None:
                    provider_session_id = observed_id
                    expected_durable_id = observed_id
                    session.pinned_durable_id = observed_id
                if raw.get("type") == "error":
                    detail = str(raw.get("text") or raw.get("message") or raw)
                    classified = classify_cursor_session_failure(
                        detail,
                        session_id=session_id,
                    )
                    if classified is not None:
                        raise classified
                    raise ProviderTurnError(
                        f"Cursor CLI error event: {detail}",
                        session_id=session_id,
                    )
                if raw.get("type") == "result":
                    session.turn_remote_observed = True
                    if raw.get("is_error"):
                        detail = str(raw.get("result") or raw.get("message") or raw)
                        classified = classify_cursor_session_failure(
                            detail,
                            session_id=session_id,
                        )
                        if classified is not None:
                            raise classified
                normalized = normalize_cursor_event(raw)
                if normalized is not None:
                    enriched = enrich_provider_observability_event(
                        normalized,
                        session_id=session_id,
                    )
                    self._emit_provider_event(enriched)
                    with session.condition:
                        if session.turn_aborted or session.turn_complete:
                            return
                        session.pending_events.append(enriched)
                        session.condition.notify_all()

            with session.condition:
                if session.turn_aborted:
                    return
            if provider_session_id is None or provider_session_id.startswith(
                _CURSOR_TRANSIENT_SESSION_PREFIX
            ):
                raise ProviderTurnError(
                    "Cursor CLI turn completed without a durable provider session id",
                    session_id=session_id,
                )
            if provider_session_id != session_id:
                raise ProviderTurnError(
                    f"Cursor CLI resume returned unexpected session id "
                    f"{provider_session_id!r} (expected {session_id!r})",
                    session_id=session_id,
                )
        finally:
            self._clear_collect_context()

    def _observe_stream_session_identity(
        self,
        session: _CursorSession,
        session_id: str,
        expected_durable_id: str | None,
        raw: dict[str, Any],
    ) -> tuple[str, str | None]:
        event_session_id = raw.get("session_id")
        if not event_session_id:
            return session_id, None
        event_session_id = str(event_session_id)
        if event_session_id.startswith(_CURSOR_TRANSIENT_SESSION_PREFIX):
            return session_id, None
        session.turn_remote_observed = True
        pinned = session.pinned_durable_id or expected_durable_id
        if pinned is not None:
            if event_session_id != pinned:
                raise ProviderSessionMismatchError(
                    "Cursor CLI resume returned unexpected session id "
                    f"{event_session_id!r} (expected {pinned!r})",
                    session_id=session_id,
                )
            return session_id, event_session_id
        session_id = self._maybe_migrate_session(session_id, event_session_id)
        session.pinned_durable_id = event_session_id
        self._set_collect_context(session_id, session.role)
        return session_id, event_session_id

    def _maybe_migrate_session(self, current_id: str, provider_session_id: str) -> str:
        if current_id == provider_session_id:
            return current_id
        if not current_id.startswith(_CURSOR_TRANSIENT_SESSION_PREFIX):
            raise ProviderSessionMismatchError(
                "Cursor CLI resume returned unexpected session id "
                f"{provider_session_id!r} (expected {current_id!r})",
                session_id=current_id,
            )

        with self._session_registry_lock:
            current = self._sessions.get(current_id)
            existing = self._sessions.get(provider_session_id)
            if existing is not None and current is not None and existing is not current:
                raise ProviderSessionError(
                    (
                        f"durable provider session {provider_session_id} is already owned "
                        f"by a different live session; refusing to migrate {current_id}"
                    ),
                    session_id=current_id,
                )
            session = self._sessions.pop(current_id, None)
            if session is None:
                session = self._require_session(provider_session_id)
                migrated_id = provider_session_id
            else:
                self._sessions[provider_session_id] = session
                self._session_aliases[current_id] = provider_session_id
                migrated_id = provider_session_id
        self._retag_tracked_turn_procs(current_id, migrated_id)
        return migrated_id

    def _retag_tracked_turn_procs(
        self,
        old_session_id: str,
        new_session_id: str,
    ) -> None:
        with self._turn_proc_lock:
            for pid, entry in list(self._tracked_turn_procs.items()):
                if entry.session_id == old_session_id:
                    self._tracked_turn_procs[pid] = replace(
                        entry,
                        session_id=new_session_id,
                    )
        context = self._get_collect_context()
        if context is not None and context[0] == old_session_id:
            self._set_collect_context(new_session_id, context[1])

    def _max_retries_per_call(self) -> int:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        return int(provider_limits.get("max_retries_per_call", 0))

    def _turn_idle_timeout_seconds(self) -> float:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        raw = provider_limits.get(
            "turn_idle_timeout_seconds",
            DEFAULT_TURN_IDLE_TIMEOUT_SECONDS,
        )
        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, timeout)

    def _agent_start_timeout_seconds(self) -> float:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        raw = provider_limits.get(
            "agent_start_timeout_seconds",
            DEFAULT_AGENT_START_TIMEOUT_SECONDS,
        )
        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_AGENT_START_TIMEOUT_SECONDS
        return max(0.0, timeout)

    @staticmethod
    def _iter_subprocess_stdout_with_idle_timeout(
        stream: _SubprocessStdoutIterator,
        *,
        idle_timeout: float,
        on_idle: Callable[[], None],
        session_id: str | None = None,
        deadline: float | None = None,
    ) -> Iterator[str]:
        while True:
            remaining = (
                idle_timeout
                if deadline is None
                else max(0.0, deadline - time.monotonic())
            )
            try:
                line = stream.read_nonempty_line(remaining)
            except StopIteration:
                return
            if line is None:
                on_idle()
                try:
                    stream.close()
                except Exception:
                    pass
                raise ProviderTurnStalledError(
                    f"provider turn produced no stream output for {idle_timeout:g}s",
                    session_id=session_id,
                )
            yield line
            if deadline is not None:
                deadline = time.monotonic() + idle_timeout

    @staticmethod
    def _iter_stream_with_idle_timeout(
        stream: Iterator[str],
        *,
        idle_timeout: float,
        on_idle: Callable[[], None],
        session_id: str | None = None,
        deadline: float | None = None,
    ) -> Iterator[str]:
        """Yield stdout lines, raising when no line arrives within *idle_timeout* seconds."""

        if isinstance(stream, _SubprocessStdoutIterator):
            yield from CursorProvider._iter_subprocess_stdout_with_idle_timeout(
                stream,
                idle_timeout=idle_timeout,
                on_idle=on_idle,
                session_id=session_id,
                deadline=deadline,
            )
            return

        line_queue: queue.Queue[str | None] = queue.Queue()
        errors: list[BaseException] = []
        stopped = threading.Event()

        def produce() -> None:
            try:
                for line in stream:
                    if stopped.is_set():
                        return
                    line_queue.put(line)
            except SystemExit:
                return
            except Exception as exc:
                errors.append(exc)
            finally:
                line_queue.put(None)

        thread = threading.Thread(
            target=produce,
            daemon=True,
            name="cursor-idle-stream",
        )
        thread.start()
        try:
            while True:
                wait = (
                    idle_timeout
                    if deadline is None
                    else max(0.0, deadline - time.monotonic())
                )
                try:
                    if wait <= 0:
                        line = line_queue.get_nowait()
                    else:
                        line = line_queue.get(timeout=wait)
                except queue.Empty:
                    on_idle()
                    closer = getattr(stream, "close", None)
                    if callable(closer):
                        try:
                            closer()
                        except Exception:
                            pass
                    stopped.set()
                    thread.join(timeout=max(idle_timeout, 0.2))
                    if thread.is_alive():
                        raise ProviderTurnError(
                            "cursor idle-stream producer failed to stop",
                            session_id=session_id,
                        )
                    raise ProviderTurnStalledError(
                        f"provider turn produced no stream output for {idle_timeout:g}s",
                        session_id=session_id,
                    )
                if line is None:
                    if errors:
                        raise errors[0]
                    break
                yield line
                if deadline is not None:
                    deadline = time.monotonic() + idle_timeout
        finally:
            stopped.set()

    def _emit_provider_event(self, event: dict[str, Any]) -> None:
        if self._on_provider_event is not None:
            self._on_provider_event(event)

    @staticmethod
    def _build_subprocess_env(
        extra_env: Mapping[str, str] | None,
    ) -> dict[str, str] | None:
        if not extra_env:
            return None
        return {**os.environ, **dict(extra_env)}

    def _set_collect_context(self, session_id: str, role: str) -> None:
        self._collect_context.session_id = session_id
        self._collect_context.role = role

    def _clear_collect_context(self) -> None:
        self._collect_context.session_id = None
        self._collect_context.role = None

    def _get_collect_context(self) -> tuple[str, str] | None:
        session_id = getattr(self._collect_context, "session_id", None)
        role = getattr(self._collect_context, "role", None)
        if isinstance(session_id, str) and isinstance(role, str):
            return session_id, role
        return None

    def _start_turn_enrichment(
        self,
        proc: subprocess.Popen[str],
        *,
        timeout: float,
    ) -> None:
        def _enrich_async() -> None:
            try:
                self._enrich_tracked_turn_proc(proc, timeout=timeout)
            except Exception:
                return

        context = self._get_collect_context()
        session_key = context[0] if context is not None else ""
        thread = threading.Thread(
            target=_enrich_async,
            daemon=True,
            name="cursor-turn-enrich",
        )
        with self._enrich_threads_lock:
            self._enrich_threads.setdefault(session_key, []).append(thread)
            thread.start()

    def _wait_turn_enrichment(
        self,
        *,
        timeout: float | None = None,
        session_id: str | None = None,
    ) -> None:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        tracked_ids = None if session_id is None else self._tracked_session_ids(session_id)
        popped_keys: list[str] = []
        threads: list[threading.Thread] = []
        with self._enrich_threads_lock:
            if tracked_ids is None:
                for key, group in self._enrich_threads.items():
                    popped_keys.append(key)
                    threads.extend(group)
                self._enrich_threads.clear()
            else:
                for key in list(self._enrich_threads):
                    if key in tracked_ids:
                        popped_keys.append(key)
                        threads.extend(self._enrich_threads.pop(key))
        still_alive: list[threading.Thread] = []
        for thread in threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining is not None and remaining <= 0 and thread.is_alive():
                still_alive.append(thread)
                continue
            thread.join(timeout=remaining)
            if thread.is_alive():
                still_alive.append(thread)
        if still_alive:
            restore_key = popped_keys[0] if popped_keys else (session_id or "")
            with self._enrich_threads_lock:
                self._enrich_threads.setdefault(restore_key, []).extend(still_alive)

    def _register_tracked_turn_proc(
        self,
        proc: subprocess.Popen[str],
        *,
        timeout: float | None = None,
    ) -> None:
        context = self._get_collect_context()
        if context is None:
            return
        with self._turn_proc_lock:
            existing = self._tracked_turn_procs.get(proc.pid)
            if existing is not None and existing.proc is proc:
                return
            if existing is not None:
                self._tracked_turn_procs.pop(proc.pid, None)
            session_id, role = context
            owner_id = getattr(self._collect_context, "owner_id", None)
            known_pgid = getattr(proc, "_core_tools_session_pgid", None)
            pgid = known_pgid if isinstance(known_pgid, int) and known_pgid > 0 else None
            self._tracked_turn_procs[proc.pid] = _TrackedTurnProc(
                session_id=session_id,
                role=role,
                proc=proc,
                pgid=pgid,
                generation=id(proc),
                owner_id=owner_id if isinstance(owner_id, str) else None,
            )
        if timeout == 0:
            return
        self._enrich_tracked_turn_proc(proc, timeout=timeout)

    def _enrich_tracked_turn_proc(
        self,
        proc: subprocess.Popen[str],
        *,
        timeout: float | None = None,
    ) -> None:
        with self._turn_proc_lock:
            entry = self._tracked_turn_procs.get(proc.pid)
        if entry is None:
            return
        run_id = self._extra_env.get("TDP_RUN_ID")
        run_id_value: str | None = run_id if isinstance(run_id, str) else None
        owner_id = entry.owner_id or self._extra_env.get(PROVIDER_OWNER_ENV_VAR)
        owner_value: str | None = owner_id if isinstance(owner_id, str) else None
        remaining = _remaining_fn(timeout)
        identity = entry.identity
        if identity is None:
            identity = read_process_identity(
                proc.pid, run_id=run_id_value, timeout=remaining()
            )
            if identity is not None and owner_value:
                identity = ProcessIdentity(
                    pid=identity.pid,
                    start_time=identity.start_time,
                    run_id=identity.run_id or run_id_value,
                    command=identity.command,
                    owner_id=owner_value,
                )
            if identity is None:
                start_time = read_process_start_time(proc.pid, timeout=remaining())
                if start_time is not None:
                    identity = ProcessIdentity(
                        pid=proc.pid,
                        start_time=start_time,
                        run_id=run_id_value,
                        owner_id=owner_value,
                    )
        pgid = entry.pgid
        if pgid is None:
            pgid = (
                read_process_group_id(proc.pid, timeout=remaining())
                if is_pid_alive(proc.pid, timeout=remaining())
                else None
            )
        members = entry.member_identities
        if identity is not None:
            captured = capture_process_group_identities(
                identity, timeout=remaining()
            )
            if captured:
                members = tuple(captured)
        with self._turn_proc_lock:
            current = self._tracked_turn_procs.get(proc.pid)
            if current is None or current is not entry or current.proc is not proc:
                return
            if current.generation and entry.generation and current.generation != entry.generation:
                return
            current.identity = identity
            current.pgid = pgid
            current.member_identities = members

    def _refresh_tracked_members(
        self,
        entry: _TrackedTurnProc,
        *,
        timeout: float | None = None,
    ) -> None:
        remaining = _remaining_fn(timeout)
        identity = entry.identity
        if identity is None and entry.proc is not None:
            identity = read_process_identity(
                entry.proc.pid, timeout=remaining()
            )
            if identity is not None:
                entry.identity = identity
        if identity is None:
            return
        captured = capture_process_group_identities(identity, timeout=remaining())
        if captured:
            entry.member_identities = tuple(captured)
        if entry.pgid is None and entry.proc is not None:
            entry.pgid = read_process_group_id(entry.proc.pid, timeout=remaining())

    def _unregister_tracked_turn_proc(self, proc: subprocess.Popen[str] | None) -> None:
        if proc is None:
            return
        self._unregister_tracked_turn_proc_by_pid(proc.pid)

    def _unregister_tracked_turn_proc_by_pid(self, pid: int) -> None:
        with self._turn_proc_lock:
            self._tracked_turn_procs.pop(pid, None)

    def _tracked_session_ids(self, session_id: str) -> set[str]:
        with self._session_registry_lock:
            canonical_id = self._session_aliases.get(session_id, session_id)
            tracked_ids = {session_id, canonical_id}
            for alias, target in self._session_aliases.items():
                if alias in tracked_ids or target in tracked_ids:
                    tracked_ids.add(alias)
                    tracked_ids.add(target)
            return tracked_ids

    @staticmethod
    def _tracked_tree_is_live(
        entry: _TrackedTurnProc,
        *,
        timeout: float | None = None,
    ) -> bool:
        remaining = _remaining_fn(timeout)
        if entry.proc is not None:
            raw_poll = entry.proc.__dict__.get("_core_tools_raw_poll", entry.proc.poll)
            if callable(raw_poll):
                try:
                    if raw_poll() is None:
                        return True
                except Exception:
                    if entry.proc.poll() is None:
                        return True
            elif entry.proc.poll() is None:
                return True
        if entry.identity is not None and process_identity_is_live(
            entry.identity, timeout=remaining()
        ):
            return True
        if entry.member_identities:
            if any(
                process_identity_is_live(identity, timeout=remaining())
                for identity in entry.member_identities
            ):
                return True
        if entry.pgid is not None:
            state = process_group_state(entry.pgid, timeout=remaining())
            if state is ProcessGroupState.GONE:
                entry.group_observed_gone = True
                return False
            if state is ProcessGroupState.UNVERIFIABLE:
                return True
            if entry.group_observed_gone:
                return False
            anchors: list[ProcessIdentity] = []
            if entry.identity is not None:
                anchors.append(entry.identity)
            if entry.member_identities:
                anchors.extend(entry.member_identities)
            states: list[IdentityInspectState] = []
            if anchors:
                states = [
                    inspect_process_identity(identity, timeout=remaining())
                    for identity in anchors
                ]
                if any(
                    state
                    in {
                        IdentityInspectState.LIVE_MATCH,
                        IdentityInspectState.ZOMBIE,
                        IdentityInspectState.UNVERIFIABLE,
                    }
                    for state in states
                ):
                    return True
            expected_run_id = (
                entry.identity.run_id if entry.identity is not None else None
            )
            expected_owner_id = entry.owner_id
            if expected_owner_id is None and entry.identity is not None:
                expected_owner_id = entry.identity.owner_id
            lineage = current_process_group_lineage(
                entry.pgid,
                expected_run_id=expected_run_id,
                expected_owner_id=expected_owner_id,
                timeout=remaining(),
            )
            if lineage is GroupLineageState.FOREIGN:
                return False
            if lineage is GroupLineageState.OWNED:
                return True
            if lineage is GroupLineageState.GONE:
                # process_group_state is LIVE; empty capture is unresolved, not gone.
                pass
            if expected_owner_id or expected_run_id:
                return True
            if not states:
                return False
            if all(
                state is IdentityInspectState.IDENTITY_MISMATCH for state in states
            ):
                return False
            return True
        # No captured PGID: a remaining process handle cannot prove descendants
        # are gone. A synthetic/stale registry row with no handle is not live.
        return entry.proc is not None

    def _historical_identities_still_present(
        self,
        entry: _TrackedTurnProc,
        *,
        timeout: float | None = None,
    ) -> bool:
        remaining = _remaining_fn(timeout)
        present = {
            IdentityInspectState.LIVE_MATCH,
            IdentityInspectState.ZOMBIE,
            IdentityInspectState.UNVERIFIABLE,
        }
        if entry.proc is not None:
            raw_poll = entry.proc.__dict__.get("_core_tools_raw_poll", entry.proc.poll)
            if callable(raw_poll):
                try:
                    if raw_poll() is None:
                        return True
                except Exception:
                    if entry.proc.poll() is None:
                        return True
            elif entry.proc.poll() is None:
                return True
        identities: list[ProcessIdentity] = []
        if entry.identity is not None:
            identities.append(entry.identity)
        if entry.member_identities:
            identities.extend(entry.member_identities)
        seen: set[tuple[int, str]] = set()
        for identity in identities:
            token = (identity.pid, identity.start_time)
            if token in seen:
                continue
            seen.add(token)
            leftover = remaining()
            if leftover is not None and leftover <= 0:
                return True
            if inspect_process_identity(identity, timeout=leftover) in present:
                return True
        return False

    def _failed_tracking_is_stale(
        self,
        entry: _TrackedTurnProc,
        *,
        timeout: float | None = None,
    ) -> bool:
        """True when a FAILED tree may be unregistered (GONE group or FOREIGN)."""

        remaining = _remaining_fn(timeout)
        if self._historical_identities_still_present(entry, timeout=remaining()):
            return False
        if entry.pgid is None:
            return False
        leftover = remaining()
        if leftover is not None and leftover <= 0:
            return False
        if entry.group_observed_gone:
            return True
        state = process_group_state(entry.pgid, timeout=leftover)
        if state is ProcessGroupState.GONE:
            entry.group_observed_gone = True
            return True
        if state is ProcessGroupState.UNVERIFIABLE:
            return False
        leftover = remaining()
        if leftover is not None and leftover <= 0:
            return False
        expected_run_id = (
            entry.identity.run_id if entry.identity is not None else None
        )
        expected_owner_id = entry.owner_id
        if expected_owner_id is None and entry.identity is not None:
            expected_owner_id = entry.identity.owner_id
        lineage = current_process_group_lineage(
            entry.pgid,
            expected_run_id=expected_run_id,
            expected_owner_id=expected_owner_id,
            timeout=leftover,
        )
        return lineage is GroupLineageState.FOREIGN

    def _prune_dead_tracked_pids_for_session(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> None:
        tracked_ids = self._tracked_session_ids(session_id)
        remaining = _remaining_fn(timeout)
        with self._turn_proc_lock:
            for pid, entry in list(self._tracked_turn_procs.items()):
                if entry.session_id in tracked_ids and not self._tracked_tree_is_live(
                    entry, timeout=remaining()
                ):
                    self._tracked_turn_procs.pop(pid, None)

    def _session_has_surviving_pids(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> bool:
        tracked_ids = self._tracked_session_ids(session_id)
        remaining = _remaining_fn(timeout)
        with self._turn_proc_lock:
            return any(
                entry.session_id in tracked_ids
                and self._tracked_tree_is_live(entry, timeout=remaining())
                for entry in self._tracked_turn_procs.values()
            )

    def _surviving_pids_for_session(
        self,
        session_id: str,
        records: list[dict[str, Any]],
        *,
        timeout: float | None = None,
    ) -> _SessionSurvival:
        tracked_ids = self._tracked_session_ids(session_id)
        surviving: set[int] = set()
        unresolved = False
        scanned: set[int] = set()
        remaining = _remaining_fn(timeout)

        def _consider_group(
            pgid: int | None,
            *,
            expected_run_id: str | None,
            expected_owner_id: str | None,
            observed_gone: bool,
        ) -> None:
            del observed_gone
            nonlocal unresolved
            if pgid is None or pgid in scanned:
                return
            scanned.add(pgid)
            leftover = remaining()
            if leftover is not None and leftover <= 0:
                unresolved = True
                return
            lineage = current_process_group_lineage(
                pgid,
                expected_run_id=expected_run_id,
                expected_owner_id=expected_owner_id,
                timeout=leftover,
            )
            if lineage is GroupLineageState.FOREIGN:
                return
            if lineage is GroupLineageState.GONE:
                return
            if lineage is GroupLineageState.UNRESOLVED:
                unresolved = True
                return
            leftover = remaining()
            if leftover is not None and leftover <= 0:
                unresolved = True
                return
            members = list_process_group_pids(pgid, timeout=leftover)
            if members is None:
                unresolved = True
                return
            for member_pid in members:
                leftover = remaining()
                if leftover is not None and leftover <= 0:
                    unresolved = True
                    return
                if is_pid_alive(member_pid, timeout=leftover):
                    surviving.add(member_pid)

        for record in records:
            if record.get("tree_status") == "stale_reconciled":
                continue
            reason = record.get("reason")
            if reason == "termination_failed":
                identities = process_identities_from_termination_record(record)
                for identity in identities:
                    leftover = remaining()
                    if leftover is not None and leftover <= 0:
                        unresolved = True
                        break
                    if process_identity_is_live(identity, timeout=leftover):
                        surviving.add(identity.pid)
            if reason in {"termination_failed", "terminated"}:
                pgid = record.get("pgid")
                _consider_group(
                    int(pgid) if isinstance(pgid, int) else None,
                    expected_run_id=record.get("run_id")
                    if isinstance(record.get("run_id"), str)
                    else None,
                    expected_owner_id=record.get("provider_owner_id")
                    if isinstance(record.get("provider_owner_id"), str)
                    else None,
                    observed_gone=bool(record.get("group_observed_gone")),
                )
        with self._turn_proc_lock:
            for pid, entry in self._tracked_turn_procs.items():
                if entry.session_id not in tracked_ids:
                    continue
                if entry.member_identities:
                    for identity in entry.member_identities:
                        leftover = remaining()
                        if leftover is not None and leftover <= 0:
                            unresolved = True
                            break
                        if process_identity_is_live(identity, timeout=leftover):
                            surviving.add(identity.pid)
                if entry.identity is not None:
                    leftover = remaining()
                    if leftover is not None and leftover <= 0:
                        unresolved = True
                    elif process_identity_is_live(entry.identity, timeout=leftover):
                        surviving.add(entry.identity.pid)
                expected_run_id = (
                    entry.identity.run_id if entry.identity is not None else None
                )
                expected_owner_id = entry.owner_id
                if expected_owner_id is None and entry.identity is not None:
                    expected_owner_id = entry.identity.owner_id
                if entry.pgid is None:
                    if entry.proc is not None:
                        unresolved = True
                    continue
                _consider_group(
                    entry.pgid,
                    expected_run_id=expected_run_id,
                    expected_owner_id=expected_owner_id,
                    observed_gone=entry.group_observed_gone,
                )
        return _SessionSurvival(pids=tuple(sorted(surviving)), unresolved=unresolved)

    def _remove_session(self, canonical_id: str) -> None:
        self._sessions.pop(canonical_id, None)
        for alias, target in list(self._session_aliases.items()):
            if target == canonical_id or alias == canonical_id:
                self._session_aliases.pop(alias, None)

    def _wrap_runner(self, runner: ProcessRunner) -> ProcessRunner:
        idle_timeout = self._turn_idle_timeout_seconds()

        def wrapped(argv: list[str], cwd: Path) -> Iterator[str]:
            active_proc: list[subprocess.Popen[str] | None] = [None]
            iterator: _SubprocessStdoutIterator | None = None
            stream: Iterator[str] | None = None
            teardown_deadline: list[float | None] = [None]
            detect_deadline: float | None = None
            owner_id = uuid.uuid4().hex
            self._collect_context.owner_id = owner_id
            turn_env = dict(self._subprocess_env or os.environ)
            turn_env[PROVIDER_OWNER_ENV_VAR] = owner_id
            try:
                if runner is default_process_runner:
                    iterator = _SubprocessStdoutIterator(
                        argv,
                        cwd,
                        env=turn_env,
                        active_proc=active_proc,
                        ready_timeout=self._agent_start_timeout_seconds(),
                        max_record_bytes=max_stream_json_record_bytes(self._config),
                    )
                    stream = iterator
                else:
                    stream = runner(argv, cwd)
                    if isinstance(stream, _SubprocessStdoutIterator):
                        iterator = stream
                        if active_proc[0] is None:
                            active_proc[0] = stream._proc
                if iterator is not None:
                    proc = active_proc[0]
                    if proc is not None:
                        self._register_tracked_turn_proc(proc, timeout=0)
                    try:
                        iterator.wait_agent_started(
                            timeout=self._agent_start_timeout_seconds()
                        )
                    except ProviderTurnStartupError:
                        proc = active_proc[0]
                        if proc is not None:
                            tracked = self._tracked_turn_procs.get(proc.pid)
                            terminate_process_tree(
                                proc,
                                pgid=tracked.pgid if tracked is not None else None,
                                leader_identity=(
                                    tracked.identity if tracked is not None else None
                                ),
                                timeout=DEFAULT_TURN_TREE_CLEANUP_SECONDS,
                            )
                        iterator.close()
                        raise
                if idle_timeout > 0:
                    detect_deadline = time.monotonic() + idle_timeout

                def on_idle() -> None:
                    proc = active_proc[0]
                    if teardown_deadline[0] is None:
                        teardown_deadline[0] = (
                            time.monotonic() + DEFAULT_TURN_TREE_CLEANUP_SECONDS
                        )
                    if proc is None:
                        return
                    tracked = self._tracked_turn_procs.get(proc.pid)
                    remaining = max(0.0, teardown_deadline[0] - time.monotonic())
                    terminate_process_tree(
                        proc,
                        pgid=tracked.pgid if tracked is not None else None,
                        leader_identity=tracked.identity if tracked is not None else None,
                        member_identities=None,
                        timeout=remaining,
                    )
                    if iterator is not None:
                        iterator.close()
                    if proc.pid in self._tracked_turn_procs:
                        live = self._tracked_tree_is_live(
                            self._tracked_turn_procs[proc.pid],
                            timeout=max(0.0, teardown_deadline[0] - time.monotonic()),
                        )
                        if not live:
                            self._unregister_tracked_turn_proc(proc)

                if idle_timeout > 0:
                    context = self._get_collect_context()
                    stalled_session_id = context[0] if context is not None else None
                    stream = self._iter_stream_with_idle_timeout(
                        stream,
                        idle_timeout=idle_timeout,
                        on_idle=on_idle,
                        session_id=stalled_session_id,
                        deadline=detect_deadline,
                    )

                assert stream is not None

                def _observe() -> Iterator[str]:
                    lines = iter(stream)
                    try:
                        first = next(lines)
                    except StopIteration:
                        return
                    yield first
                    proc = active_proc[0]
                    if proc is not None:
                        enrich_timeout = max(
                            0.05, min(0.5, self._agent_start_timeout_seconds())
                        )
                        self._start_turn_enrichment(proc, timeout=enrich_timeout)
                    yield from lines

                yield from _observe()
            finally:
                if teardown_deadline[0] is None:
                    teardown_deadline[0] = (
                        time.monotonic() + DEFAULT_TURN_TREE_CLEANUP_SECONDS
                    )
                context = self._get_collect_context()
                wait_session_id = context[0] if context is not None else None
                remaining = max(0.0, teardown_deadline[0] - time.monotonic())
                self._wait_turn_enrichment(
                    timeout=remaining,
                    session_id=wait_session_id,
                )
                proc = active_proc[0]
                try:
                    if proc is not None:
                        tracked = self._tracked_turn_procs.get(proc.pid)
                        returncode = proc.poll()
                        status = getattr(proc, "_core_tools_janitor_status", None)
                        if tracked is not None and janitor_group_was_cleaned(
                            returncode if returncode is not None else 1,
                            status if isinstance(status, dict) else None,
                        ):
                            tracked.group_observed_gone = True
                        if tracked is not None:
                            self._refresh_tracked_members(
                                tracked,
                                timeout=max(
                                    0.0, teardown_deadline[0] - time.monotonic()
                                ),
                            )
                        tree_clean = terminate_process_tree(
                            proc,
                            pgid=tracked.pgid if tracked is not None else None,
                            leader_identity=tracked.identity if tracked is not None else None,
                            member_identities=(
                                list(tracked.member_identities)
                                if tracked is not None and tracked.member_identities is not None
                                else None
                            ),
                            timeout=max(
                                0.0, teardown_deadline[0] - time.monotonic()
                            ),
                        )
                        if tree_clean:
                            self._unregister_tracked_turn_proc(proc)
                finally:
                    if iterator is not None:
                        iterator.close()

        return wrapped
