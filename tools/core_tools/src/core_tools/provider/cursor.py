"""Thin Cursor CLI provider adapter (proposal §16)."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_tools.provider.cursor_session_errors import (
    classify_cursor_session_failure,
    reclassify_provider_turn_error,
)
from core_tools.provider.errors import (
    ProviderBinaryNotFoundError,
    ProviderSessionError,
    ProviderSessionNotFoundError,
    ProviderSessionTerminationError,
    ProviderTurnError,
    ProviderTurnStalledError,
)
from core_tools.provider.events import (
    format_manifest_prompt,
    format_request_prompt,
    normalize_cursor_event,
)
from core_tools.provider.process_cleanup import (
    is_pid_alive,
    terminate_pid_tree,
    terminate_process_tree,
)

_CURSOR_TRANSIENT_SESSION_PREFIX = "cursor-pending-"
_STDERR_TAIL_MAX_BYTES = 64 * 1024

ProcessRunner = Callable[[list[str], Path], Iterator[str]]
ProviderEventCallback = Callable[[dict[str, Any]], None]


class _SubprocessStdoutIterator(Iterator[str]):
    """Eager-start subprocess runner so callers can track PID before first stdout line."""

    def __init__(
        self,
        argv: list[str],
        cwd: Path,
        *,
        env: Mapping[str, str] | None = None,
        active_proc: list[subprocess.Popen[str] | None] | None = None,
    ) -> None:
        popen_kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if env is not None:
            popen_kwargs["env"] = dict(env)
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True

        try:
            self._proc = subprocess.Popen(argv, **popen_kwargs)
        except OSError as exc:
            raise ProviderTurnError(f"failed to start Cursor CLI: {exc}") from exc

        if active_proc is not None:
            active_proc[0] = self._proc

        if self._proc.stdout is None:
            if active_proc is not None:
                active_proc[0] = None
            raise ProviderTurnError("Cursor CLI stdout pipe was not available")

        self._active_proc = active_proc
        self._stderr_tail = bytearray()
        self._stderr_truncated = False
        self._stderr_done = threading.Event()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._finished = False

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
                chunk = self._proc.stderr.buffer.read(8192)
                if not chunk:
                    break
                self._append_stderr_bytes(chunk)
        finally:
            self._stderr_done.set()

    def __iter__(self) -> _SubprocessStdoutIterator:
        return self

    def __next__(self) -> str:
        if self._finished:
            raise StopIteration
        while True:
            if self._proc.poll() is not None:
                if self._proc.stdout is not None:
                    for line in self._proc.stdout:
                        stripped = line.strip()
                        if stripped:
                            return stripped
                self._finalize()
                raise StopIteration
            if self._proc.stdout is None:
                self._finalize()
                raise StopIteration
            line = self._proc.stdout.readline()
            if not line:
                self._finalize()
                raise StopIteration
            stripped = line.strip()
            if stripped:
                return stripped

    def _finalize(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._stderr_done.wait(timeout=5)
        stderr = self._stderr_tail.decode("utf-8", errors="replace")
        if self._stderr_truncated:
            stderr = (
                f"[stderr truncated; showing last {_STDERR_TAIL_MAX_BYTES} bytes]\n"
                f"{stderr}"
            )
        return_code = self._proc.wait()
        if return_code != 0:
            detail = stderr.strip() or f"exit code {return_code}"
            raise ProviderTurnError(f"Cursor CLI failed: {detail}")
        if self._active_proc is not None:
            self._active_proc[0] = None


def default_process_runner(
    argv: list[str],
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
    active_proc: list[subprocess.Popen[str] | None] | None = None,
) -> Iterator[str]:
    """Run the Cursor CLI and yield stdout lines."""

    return _SubprocessStdoutIterator(
        argv,
        cwd,
        env=env,
        active_proc=active_proc,
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
    turn_running: bool = False
    turn_complete: bool = False
    turn_aborted: bool = False
    turn_error: ProviderTurnError | None = None
    collector_thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    condition: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        self.condition = threading.Condition(self.lock)


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
        self._turn_proc_lock = threading.Lock()
        self._tracked_turn_procs: dict[int, tuple[str, str]] = {}
        self._collect_context = threading.local()
        self._on_provider_event = on_provider_event
        self._shutting_down = False

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
            with session.condition:
                while not session.pending_events and not session.turn_complete:
                    session.condition.wait(timeout=0.05)
                if session.pending_events:
                    yield session.pending_events.popleft()
                    continue
                if session.turn_complete:
                    if session.turn_error is not None:
                        raise session.turn_error
                    break

    def canonical_session_id(self, session_id: str) -> str:
        return self._session_aliases.get(session_id, session_id)

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
        return [
            {
                "session_id": session_id,
                "role": session.role,
                "kind": session.kind,
                "model": format_provider_model_name(session.model),
            }
            for session_id, session in self._sessions.items()
        ]

    def terminate_session(self, session_id: str) -> None:
        canonical_id = self.canonical_session_id(session_id)
        self.abort_turn(canonical_id)
        self.wait_turn_settled(canonical_id)
        records = self._terminate_tracked_turn_procs_for_session(canonical_id)
        surviving_pids = self._surviving_pids_for_session(canonical_id, records)
        if surviving_pids:
            raise ProviderSessionTerminationError(
                (
                    f"failed to terminate provider session {canonical_id}: "
                    f"surviving agent processes {list(surviving_pids)}"
                ),
                session_id=canonical_id,
                surviving_pids=surviving_pids,
            )
        self._remove_session(canonical_id)

    def abort_turn(self, session_id: str) -> None:
        """End the current in-flight turn without dropping the durable session.

        Marks the turn aborted and wakes ``stream_events`` waiters. Callers that
        need the collector thread to finish must invoke ``wait_turn_settled`` after
        draining or closing the turn.
        """

        canonical_id = self.canonical_session_id(session_id)
        session = self._sessions.get(canonical_id)
        if session is None:
            return
        with session.condition:
            session.pending_events.clear()
            session.turn_aborted = True
        self._abort_session_turn(session, error=None)
        self._terminate_tracked_turn_procs_for_session(canonical_id)

    def terminate_all_sessions(self) -> list[dict[str, Any]]:
        """Stop in-flight turns and drop tracked provider sessions."""

        self._shutting_down = True
        terminated: list[dict[str, Any]] = []
        self._abort_inflight_sessions()
        terminated.extend(self._terminate_tracked_turn_procs())

        for session in list(self._sessions.values()):
            thread = session.collector_thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.5)

        terminated.extend(self._terminate_tracked_turn_procs())

        for session_id in list(self._sessions.keys()):
            if not self._session_has_surviving_pids(session_id):
                self._remove_session(session_id)

        self._shutting_down = False
        return terminated

    def _terminate_tracked_turn_procs(
        self,
        *,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        terminated: list[dict[str, Any]] = []
        with self._turn_proc_lock:
            tracked = dict(self._tracked_turn_procs)

        tracked_ids = (
            self._tracked_session_ids(session_id) if session_id is not None else None
        )
        seen_pids: set[int] = set()
        for pid, (tracked_session_id, role) in tracked.items():
            if tracked_ids is not None and tracked_session_id not in tracked_ids:
                continue
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            if is_pid_alive(pid):
                if terminate_pid_tree(pid):
                    terminated.append(
                        {
                            "pid": pid,
                            "role": role,
                            "session_id": tracked_session_id,
                            "reason": "terminated",
                        }
                    )
                    self._unregister_tracked_turn_proc_by_pid(pid)
                else:
                    terminated.append(
                        {
                            "pid": pid,
                            "role": role,
                            "session_id": tracked_session_id,
                            "reason": "termination_failed",
                        }
                    )
            else:
                self._unregister_tracked_turn_proc_by_pid(pid)
        return terminated

    def _terminate_tracked_turn_procs_for_session(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        return self._terminate_tracked_turn_procs(session_id=session_id)

    def _abort_session_turn(
        self,
        session: _CursorSession,
        *,
        error: ProviderTurnError | None,
    ) -> None:
        with session.condition:
            session.turn_running = False
            session.turn_complete = True
            if error is not None:
                session.turn_error = error
            session.condition.notify_all()

    def _abort_inflight_sessions(self) -> None:
        for session_id, session in list(self._sessions.items()):
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
        self._register_session(
            role=role,
            kind=kind,
            manifest={},
            prompt="",
            model=model,
            resume_session_id=canonical_id,
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
        session_id = resume_session_id or self._new_pending_session_id()
        self._sessions[session_id] = _CursorSession(
            role=role,
            kind=kind,
            manifest=dict(manifest),
            model=session_model,
            pending_argv=argv,
        )
        return session_id

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        """Block until the in-flight collector thread for this session has finished."""

        canonical_id = self.canonical_session_id(session_id)
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
            session.pending_events.clear()
            session.pending_argv = argv
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
                self._collect_turn_stream(session_id, session, argv)
                return
            except ProviderTurnError as exc:
                if isinstance(exc, ProviderTurnStalledError):
                    raise exc
                classified = reclassify_provider_turn_error(exc, session_id=session_id)
                if isinstance(classified, ProviderSessionNotFoundError):
                    raise classified from exc
                if self._session_turn_aborted(session):
                    raise ProviderTurnError(
                        "provider session terminated",
                        session_id=session_id,
                    ) from exc
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
        expected_durable_id: str | None = None
        if not session_id.startswith(_CURSOR_TRANSIENT_SESSION_PREFIX):
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
                if raw.get("type") == "result" and raw.get("is_error"):
                    detail = str(raw.get("result") or raw.get("message") or raw)
                    classified = classify_cursor_session_failure(
                        detail,
                        session_id=session_id,
                    )
                    if classified is not None:
                        raise classified
                if raw.get("session_id"):
                    event_session_id = str(raw["session_id"])
                    if not event_session_id.startswith(_CURSOR_TRANSIENT_SESSION_PREFIX):
                        if expected_durable_id is not None:
                            if event_session_id != expected_durable_id:
                                raise ProviderTurnError(
                                    "Cursor CLI resume returned unexpected session id "
                                    f"{event_session_id!r} (expected {expected_durable_id!r})",
                                    session_id=session_id,
                                )
                            provider_session_id = event_session_id
                        else:
                            session_id = self._maybe_migrate_session(
                                session_id,
                                event_session_id,
                            )
                            self._set_collect_context(session_id, session.role)
                            provider_session_id = event_session_id
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

    def _maybe_migrate_session(self, current_id: str, provider_session_id: str) -> str:
        if current_id == provider_session_id:
            return current_id

        session = self._sessions.pop(current_id, None)
        if session is None:
            session = self._require_session(provider_session_id)
            self._retag_tracked_turn_procs(current_id, provider_session_id)
            return provider_session_id

        self._sessions[provider_session_id] = session
        self._session_aliases[current_id] = provider_session_id
        self._retag_tracked_turn_procs(current_id, provider_session_id)
        return provider_session_id

    def _retag_tracked_turn_procs(
        self,
        old_session_id: str,
        new_session_id: str,
    ) -> None:
        with self._turn_proc_lock:
            for pid, (tracked_session_id, role) in list(self._tracked_turn_procs.items()):
                if tracked_session_id == old_session_id:
                    self._tracked_turn_procs[pid] = (new_session_id, role)
        context = self._get_collect_context()
        if context is not None and context[0] == old_session_id:
            self._set_collect_context(new_session_id, context[1])

    def _max_retries_per_call(self) -> int:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        return int(provider_limits.get("max_retries_per_call", 0))

    def _turn_idle_timeout_seconds(self) -> float:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        raw = provider_limits.get("turn_idle_timeout_seconds", 0)
        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, timeout)

    @staticmethod
    def _iter_stream_with_idle_timeout(
        stream: Iterator[str],
        *,
        idle_timeout: float,
        on_idle: Callable[[], None],
        session_id: str | None = None,
    ) -> Iterator[str]:
        """Yield stdout lines, raising when no line arrives within *idle_timeout* seconds."""

        line_queue: queue.Queue[str | None] = queue.Queue()
        errors: list[BaseException] = []

        def produce() -> None:
            try:
                for line in stream:
                    line_queue.put(line)
            except Exception as exc:
                errors.append(exc)
            finally:
                line_queue.put(None)

        thread = threading.Thread(target=produce, daemon=True)
        thread.start()
        while True:
            try:
                line = line_queue.get(timeout=idle_timeout)
            except queue.Empty:
                on_idle()
                raise ProviderTurnStalledError(
                    f"provider turn produced no stream output for {idle_timeout:g}s",
                    session_id=session_id,
                )
            if line is None:
                if errors:
                    raise errors[0]
                break
            yield line

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

    def _register_tracked_turn_proc(self, proc: subprocess.Popen[str]) -> None:
        context = self._get_collect_context()
        if context is None:
            return
        session_id, role = context
        with self._turn_proc_lock:
            self._tracked_turn_procs[proc.pid] = (session_id, role)

    def _unregister_tracked_turn_proc(self, proc: subprocess.Popen[str] | None) -> None:
        if proc is None:
            return
        self._unregister_tracked_turn_proc_by_pid(proc.pid)

    def _unregister_tracked_turn_proc_by_pid(self, pid: int) -> None:
        with self._turn_proc_lock:
            self._tracked_turn_procs.pop(pid, None)

    def _tracked_session_ids(self, session_id: str) -> set[str]:
        canonical_id = self.canonical_session_id(session_id)
        tracked_ids = {session_id, canonical_id}
        for alias, target in self._session_aliases.items():
            if alias in tracked_ids or target in tracked_ids:
                tracked_ids.add(alias)
                tracked_ids.add(target)
        return tracked_ids

    def _session_has_surviving_pids(self, session_id: str) -> bool:
        tracked_ids = self._tracked_session_ids(session_id)
        with self._turn_proc_lock:
            return any(
                tracked_session_id in tracked_ids and is_pid_alive(pid)
                for pid, (tracked_session_id, _role) in self._tracked_turn_procs.items()
            )

    def _surviving_pids_for_session(
        self,
        session_id: str,
        records: list[dict[str, Any]],
    ) -> tuple[int, ...]:
        tracked_ids = self._tracked_session_ids(session_id)
        surviving = {
            int(record["pid"])
            for record in records
            if record.get("reason") == "termination_failed"
            and isinstance(record.get("pid"), int)
            and is_pid_alive(int(record["pid"]))
        }
        with self._turn_proc_lock:
            for pid, (tracked_session_id, _role) in self._tracked_turn_procs.items():
                if tracked_session_id in tracked_ids and is_pid_alive(pid):
                    surviving.add(pid)
        return tuple(sorted(surviving))

    def _remove_session(self, canonical_id: str) -> None:
        self._sessions.pop(canonical_id, None)
        for alias, target in list(self._session_aliases.items()):
            if target == canonical_id or alias == canonical_id:
                self._session_aliases.pop(alias, None)

    def _wrap_runner(self, runner: ProcessRunner) -> ProcessRunner:
        idle_timeout = self._turn_idle_timeout_seconds()

        def wrapped(argv: list[str], cwd: Path) -> Iterator[str]:
            active_proc: list[subprocess.Popen[str] | None] = [None]
            try:
                if runner is default_process_runner:
                    stream = default_process_runner(
                        argv,
                        cwd,
                        env=self._subprocess_env,
                        active_proc=active_proc,
                    )
                else:
                    stream = runner(argv, cwd)

                def on_idle() -> None:
                    proc = active_proc[0]
                    if proc is not None and proc.poll() is None:
                        terminate_process_tree(proc)

                if idle_timeout > 0:
                    context = self._get_collect_context()
                    stalled_session_id = context[0] if context is not None else None
                    stream = self._iter_stream_with_idle_timeout(
                        stream,
                        idle_timeout=idle_timeout,
                        on_idle=on_idle,
                        session_id=stalled_session_id,
                    )

                if active_proc[0] is not None:
                    self._register_tracked_turn_proc(active_proc[0])

                for line in stream:
                    if active_proc[0] is not None:
                        self._register_tracked_turn_proc(active_proc[0])
                    yield line
            finally:
                proc = active_proc[0]
                if proc is not None:
                    if proc.poll() is None:
                        terminate_process_tree(proc)
                    if proc.poll() is not None or not is_pid_alive(proc.pid):
                        self._unregister_tracked_turn_proc(proc)

        return wrapped
