"""Thin Cursor CLI provider adapter (proposal §16)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def _resolve_cli_model(*, model: str | None = None) -> str | None:
    if model is None:
        return None
    resolved = str(model).strip()
    if not resolved or resolved.lower() == "auto":
        return None
    return resolved


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

    resolved_model = _resolve_cli_model(model=model)
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
        self._active_turn_proc: subprocess.Popen[str] | None = None

    def start_primary_session(
        self,
        role: str,
        context_manifest: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        return self._start_session(
            role=role,
            kind="primary",
            manifest=context_manifest,
            prompt=format_manifest_prompt(role, context_manifest),
            model=model,
        )

    def resume_primary_session(self, session_id: str, request: dict[str, Any]) -> None:
        self._execute_turn(session_id, prompt=format_request_prompt(request))

    def start_reviewer_session(
        self,
        review_package: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        return self._start_session(
            role="reviewer",
            kind="reviewer",
            manifest=review_package,
            prompt=format_request_prompt(review_package),
            model=model,
        )

    def send(self, session_id: str, request: dict[str, Any]) -> None:
        self._execute_turn(session_id, prompt=format_request_prompt(request))

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        session = self._require_session(session_id)
        while session.pending_events:
            yield session.pending_events.popleft()

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
        session = self._require_session(session_id)
        return {
            "provider": "cursor",
            "session_id": session_id,
            "role": session.role,
            "kind": session.kind,
            "model": session.model,
            "binary": self._binary,
            "workspace": str(self._workspace),
        }

    def terminate_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def terminate_all_sessions(self) -> None:
        """Stop in-flight turns and drop tracked provider sessions."""

        self._terminate_active_turn()
        self._sessions.clear()

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
        session = self._sessions.get(session_id)
        if session is None:
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )
        return session

    def _start_session(
        self,
        *,
        role: str,
        kind: str,
        manifest: dict[str, Any],
        prompt: str,
        model: str | None = None,
    ) -> str:
        session_model = _resolve_cli_model(model=model)
        argv = build_agent_argv(
            self._config,
            binary=self._binary,
            workspace=self._workspace,
            session_id=None,
            prompt=prompt,
            model=session_model,
        )
        events, provider_session_id = self._collect_events(argv)
        if provider_session_id is None:
            raise ProviderTurnError(
                "Cursor CLI turn completed without a provider session id"
            )
        self._sessions[provider_session_id] = _CursorSession(
            role=role,
            kind=kind,
            manifest=dict(manifest),
            model=session_model,
            pending_events=deque(events),
        )
        return provider_session_id

    def _execute_turn(self, session_id: str, *, prompt: str) -> None:
        session = self._require_session(session_id)
        argv = build_agent_argv(
            self._config,
            binary=self._binary,
            workspace=self._workspace,
            session_id=session_id,
            prompt=prompt,
            model=session.model,
        )
        events, provider_session_id = self._collect_events(argv)
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
        session.pending_events = deque(events)

    def _max_retries_per_call(self) -> int:
        provider_limits = (self._config.get("limits") or {}).get("provider") or {}
        return int(provider_limits.get("max_retries_per_call", 0))

    def _collect_events(
        self,
        argv: list[str],
    ) -> tuple[list[dict[str, Any]], str | None]:
        max_retries = self._max_retries_per_call()
        last_error: ProviderTurnError | None = None
        for attempt in range(max_retries + 1):
            try:
                return self._collect_events_once(argv)
            except ProviderTurnError as exc:
                last_error = exc
                if attempt >= max_retries:
                    raise
        if last_error is not None:
            raise last_error
        return [], None

    def _collect_events_once(
        self,
        argv: list[str],
    ) -> tuple[list[dict[str, Any]], str | None]:
        events: list[dict[str, Any]] = []
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
            normalized = normalize_cursor_event(raw)
            if normalized is not None:
                events.append(normalized)

        return events, provider_session_id

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
