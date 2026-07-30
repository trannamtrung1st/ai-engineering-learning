"""Deterministic stub provider for tests (no subprocess)."""

from __future__ import annotations

import copy
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from core_tools.provider.errors import ProviderSessionError, ProviderTurnError
from core_tools.provider.events import format_manifest_prompt, format_request_prompt

ProviderEventCallback = Callable[[dict[str, Any]], None]


@dataclass
class _StubSession:
    role: str
    kind: str
    manifest: dict[str, Any]
    model: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    pending_events: deque[dict[str, Any]] = field(default_factory=deque)


class StubProvider:
    """Scriptable provider with queueable turn responses."""

    def __init__(
        self,
        *,
        on_provider_event: ProviderEventCallback | None = None,
    ) -> None:
        self._sessions: dict[str, _StubSession] = {}
        self._default_scripts: list[list[dict[str, Any]]] = []
        self._session_scripts: dict[str, list[list[dict[str, Any]]]] = {}
        self._counter = 0
        self._capability_token: str | None = None
        self._on_provider_event = on_provider_event

    def script_turn(self, events: list[dict[str, Any]]) -> None:
        """Queue scripted normalized events for the next turn on any session."""

        self._default_scripts.append(copy.deepcopy(events))

    def script_session_turn(self, session_id: str, events: list[dict[str, Any]]) -> None:
        """Queue scripted events for the next turn on a specific session."""

        scripts = self._session_scripts.setdefault(session_id, [])
        scripts.append(copy.deepcopy(events))

    def start_primary_session(
        self,
        role: str,
        context_manifest: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        session_id = self._new_session_id()
        self._sessions[session_id] = _StubSession(
            role=role,
            kind="primary",
            manifest=copy.deepcopy(context_manifest),
            model=model,
        )
        prompt = format_manifest_prompt(role, context_manifest)
        self._enqueue_turn(session_id, {"prompt": prompt, "kind": "start"})
        return session_id

    def resume_primary_session(self, session_id: str, request: dict[str, Any]) -> None:
        self._enqueue_turn(session_id, request)

    def start_reviewer_session(
        self,
        review_package: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        session_id = self._new_session_id()
        self._sessions[session_id] = _StubSession(
            role="reviewer",
            kind="reviewer",
            manifest=copy.deepcopy(review_package),
            model=model,
        )
        prompt = format_request_prompt(review_package)
        self._enqueue_turn(session_id, {"prompt": prompt, "kind": "start"})
        return session_id

    def send(self, session_id: str, request: dict[str, Any]) -> None:
        self._enqueue_turn(session_id, request)

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        session = self._require_session(session_id)
        while session.pending_events:
            yield session.pending_events.popleft()

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "provider": "stub",
            "models": ["stub-model"],
            "features": {"resume": True, "stream_json": True},
        }

    def get_session_reference(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        return {
            "provider": "stub",
            "session_id": session_id,
            "role": session.role,
            "kind": session.kind,
            "model": session.model,
            "turn_count": len(session.history),
        }

    def terminate_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def terminate_all_sessions(self) -> None:
        self._sessions.clear()

    def set_capability_token(self, token: str | None) -> None:
        self._capability_token = token

    def _new_session_id(self) -> str:
        self._counter += 1
        return f"stub-session-{self._counter}"

    def _require_session(self, session_id: str) -> _StubSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )
        return session

    def _enqueue_turn(self, session_id: str, request: dict[str, Any]) -> None:
        session = self._require_session(session_id)
        session.history.append(copy.deepcopy(request))
        scripted = self._resolve_script(session_id)
        for event in scripted:
            normalized = copy.deepcopy(event)
            normalized.setdefault("session_id", session_id)
            self._emit_provider_event(normalized)
            session.pending_events.append(normalized)

    def _emit_provider_event(self, event: dict[str, Any]) -> None:
        if self._on_provider_event is not None:
            self._on_provider_event(event)

    def _resolve_script(self, session_id: str) -> list[dict[str, Any]]:
        session_scripts = self._session_scripts.get(session_id)
        if session_scripts:
            return session_scripts.pop(0)
        if self._default_scripts:
            return self._default_scripts.pop(0)
        raise ProviderTurnError(
            f"no scripted provider turn configured for session {session_id}",
            session_id=session_id,
        )
