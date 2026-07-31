"""Thin Cursor CLI provider adapter (proposal §16)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_tools.provider.errors import (
    ProviderBinaryNotFoundError,
    ProviderSessionError,
    ProviderTurnError,
)
from core_tools.provider.events import (
    format_manifest_prompt,
    format_request_prompt,
    normalize_cursor_event,
)
from core_tools.provider.process_cleanup import terminate_process_tree

ProcessRunner = Callable[[list[str], Path], Iterator[str]]
ProviderEventCallback = Callable[[dict[str, Any]], None]


def default_process_runner(
    argv: list[str],
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
    active_proc: list[subprocess.Popen[str] | None] | None = None,
) -> Iterator[str]:
    """Run the Cursor CLI and yield stdout lines."""

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
        proc = subprocess.Popen(argv, **popen_kwargs)
    except OSError as exc:
        raise ProviderTurnError(f"failed to start Cursor CLI: {exc}") from exc

    if active_proc is not None:
        active_proc[0] = proc

    if proc.stdout is None:
        if active_proc is not None:
            active_proc[0] = None
        raise ProviderTurnError("Cursor CLI stdout pipe was not available")

    try:
        for line in proc.stdout:
            stripped = line.strip()
            if stripped:
                yield stripped

        stderr = proc.stderr.read() if proc.stderr is not None else ""
        return_code = proc.wait()
        if return_code != 0:
            detail = stderr.strip() or f"exit code {return_code}"
            raise ProviderTurnError(f"Cursor CLI failed: {detail}")
    finally:
        if active_proc is not None:
            active_proc[0] = None


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
    """Return the observability label for a provider-resolved model."""

    resolved = resolve_provider_cli_model(model=model)
    if resolved is None:
        return "auto"
    return resolved


def enrich_provider_observability_event(
    event: dict[str, Any],
    *,
    session_id: str,
    model: str | None,
) -> dict[str, Any]:
    """Attach session identity and resolved model label to a provider event."""

    enriched = dict(event)
    enriched["session_id"] = session_id
    enriched["model"] = format_provider_model_name(model)
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

    if session_id:
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
        self._active_turn_proc: subprocess.Popen[str] | None = None
        self._on_provider_event = on_provider_event

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
        self, session_id: str, request: dict[str, Any], *, model: str | None = None
    ) -> None:
        canonical_id = self._ensure_durable_session(
            session_id,
            role="primary",
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
        self._sessions.pop(canonical_id, None)
        for alias, target in list(self._session_aliases.items()):
            if target == canonical_id or alias == canonical_id:
                self._session_aliases.pop(alias, None)

    def terminate_all_sessions(self) -> None:
        """Stop in-flight turns and drop tracked provider sessions."""

        self._terminate_active_turn()
        self._sessions.clear()
        self._session_aliases.clear()

    def set_capability_token(self, token: str | None) -> None:
        if token:
            self._extra_env["TDP_CAPABILITY_TOKEN"] = token
        else:
            self._extra_env.pop("TDP_CAPABILITY_TOKEN", None)
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
            return canonical_id
        if canonical_id.startswith("cursor-pending-"):
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
        return f"cursor-pending-{self._pending_counter}"

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

    def _queue_turn(self, session_id: str, *, prompt: str) -> None:
        session = self._require_session(session_id)
        if session.turn_running:
            raise ProviderTurnError(
                f"provider turn already in progress for session {session_id}",
                session_id=session_id,
            )
        argv = build_agent_argv(
            self._config,
            binary=self._binary,
            workspace=self._workspace,
            session_id=session_id,
            prompt=prompt,
            model=session.model,
        )
        with session.condition:
            session.pending_events.clear()
            session.pending_argv = argv
            session.turn_running = False
            session.turn_complete = False
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
        except ProviderTurnError as exc:
            with session.condition:
                session.turn_error = exc
        finally:
            with session.condition:
                session.turn_running = False
                session.turn_complete = True
                session.condition.notify_all()

    def _collect_turn_once(
        self,
        session_id: str,
        session: _CursorSession,
        argv: list[str],
    ) -> None:
        max_retries = self._max_retries_per_call()
        last_error: ProviderTurnError | None = None
        for attempt in range(max_retries + 1):
            try:
                self._collect_turn_stream(session_id, session, argv)
                return
            except ProviderTurnError as exc:
                last_error = exc
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
                            model=session.model,
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

        for line in self._runner(argv, self._workspace):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderTurnError(
                    f"invalid stream-json line from Cursor CLI: {line!r}"
                ) from exc
            if not isinstance(raw, dict):
                continue
            if raw.get("session_id"):
                provider_session_id = str(raw["session_id"])
                session_id = self._maybe_migrate_session(session_id, provider_session_id)
            normalized = normalize_cursor_event(raw)
            if normalized is not None:
                enriched = enrich_provider_observability_event(
                    normalized,
                    session_id=session_id,
                    model=session.model,
                )
                self._emit_provider_event(enriched)
                with session.condition:
                    session.pending_events.append(enriched)
                    session.condition.notify_all()

        if provider_session_id is None:
            raise ProviderTurnError(
                "Cursor CLI turn completed without a provider session id",
                session_id=session_id,
            )
        if provider_session_id != session_id:
            raise ProviderTurnError(
                f"Cursor CLI resume returned unexpected session id "
                f"{provider_session_id!r} (expected {session_id!r})",
                session_id=session_id,
            )

    def _maybe_migrate_session(self, current_id: str, provider_session_id: str) -> str:
        if current_id == provider_session_id:
            return current_id

        session = self._sessions.pop(current_id, None)
        if session is None:
            session = self._require_session(provider_session_id)
            return provider_session_id

        self._sessions[provider_session_id] = session
        self._session_aliases[current_id] = provider_session_id
        return provider_session_id

    def _max_retries_per_call(self) -> int:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        return int(provider_limits.get("max_retries_per_call", 0))

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

    def _terminate_active_turn(self) -> None:
        proc = self._active_turn_proc
        if proc is None:
            return
        self._active_turn_proc = None
        terminate_process_tree(proc)

    def _wrap_runner(self, runner: ProcessRunner) -> ProcessRunner:
        active_proc: list[subprocess.Popen[str] | None] = [None]

        def wrapped(argv: list[str], cwd: Path) -> Iterator[str]:
            self._active_turn_proc = None
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
                for line in stream:
                    if active_proc[0] is not None:
                        self._active_turn_proc = active_proc[0]
                    yield line
            finally:
                self._active_turn_proc = None
                proc = active_proc[0]
                if proc is not None and proc.poll() is None:
                    terminate_process_tree(proc)

        return wrapped
