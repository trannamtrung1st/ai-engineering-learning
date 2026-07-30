"""Thin Cursor CLI provider adapter (proposal §16)."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import deque
from collections.abc import Callable, Iterator
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

ProcessRunner = Callable[[list[str], Path], Iterator[str]]


def default_process_runner(argv: list[str], cwd: Path) -> Iterator[str]:
    """Run the Cursor CLI and yield stdout lines."""

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise ProviderTurnError(f"failed to start Cursor CLI: {exc}") from exc

    if proc.stdout is None:
        raise ProviderTurnError("Cursor CLI stdout pipe was not available")

    for line in proc.stdout:
        stripped = line.strip()
        if stripped:
            yield stripped

    stderr = proc.stderr.read() if proc.stderr is not None else ""
    return_code = proc.wait()
    if return_code != 0:
        detail = stderr.strip() or f"exit code {return_code}"
        raise ProviderTurnError(f"Cursor CLI failed: {detail}")


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


def build_agent_argv(
    config: dict[str, Any],
    *,
    binary: str,
    workspace: Path,
    session_id: str | None = None,
    prompt: str | None = None,
) -> list[str]:
    """Construct a Cursor CLI argv for a non-interactive streamed turn."""

    provider_cfg = config.get("provider") or {}
    argv: list[str] = [
        binary,
        "--print",
        "--output-format",
        "stream-json",
        "--trust",
        "--approve-mcps",
        "--workspace",
        str(workspace),
    ]

    model = provider_cfg.get("model")
    if model:
        argv.extend(["--model", str(model)])

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
    ) -> None:
        self._config = config
        provider_cfg = config.get("provider") or {}
        self._workspace = Path(workspace or Path.cwd()).resolve()
        self._runner = runner or default_process_runner
        self._skip_probe = bool(skip_probe or provider_cfg.get("skip_probe"))
        configured_binary = binary or provider_cfg.get("binary")
        self._binary = resolve_agent_binary(
            str(configured_binary) if configured_binary else None
        )
        if not self._skip_probe:
            self._probe_binary()
        self._sessions: dict[str, _CursorSession] = {}

    def start_primary_session(
        self, role: str, context_manifest: dict[str, Any]
    ) -> str:
        return self._start_session(
            role=role,
            kind="primary",
            manifest=context_manifest,
            prompt=format_manifest_prompt(role, context_manifest),
        )

    def resume_primary_session(self, session_id: str, request: dict[str, Any]) -> None:
        self._execute_turn(session_id, prompt=format_request_prompt(request))

    def start_reviewer_session(self, review_package: dict[str, Any]) -> str:
        return self._start_session(
            role="reviewer",
            kind="reviewer",
            manifest=review_package,
            prompt=format_request_prompt(review_package),
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
            "config": {
                "use_native_project_context": bool(
                    provider_cfg.get("use_native_project_context", True)
                ),
            },
        }

    def get_session_reference(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        return {
            "provider": "cursor",
            "session_id": session_id,
            "role": session.role,
            "kind": session.kind,
            "binary": self._binary,
            "workspace": str(self._workspace),
        }

    def terminate_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _probe_binary(self) -> None:
        try:
            proc = subprocess.run(
                [self._binary, "--version"],
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                check=False,
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
    ) -> str:
        argv = build_agent_argv(
            self._config,
            binary=self._binary,
            workspace=self._workspace,
            session_id=None,
            prompt=prompt,
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

    def _collect_events(
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
