"""Provider contract for session lifecycle and messaging."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol


class Provider(Protocol):
    """Abstract provider for planner, producer, and reviewer sessions."""

    def start_primary_session(
        self,
        role: str,
        context_manifest: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        """Start a new primary session and return its provider session id."""

    def resume_primary_session(
        self, session_id: str, request: dict[str, Any]
    ) -> None:
        """Resume an existing primary session with a follow-up request."""

    def start_reviewer_session(
        self,
        review_package: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        """Start a fresh reviewer session for a bounded review package."""

    def send(self, session_id: str, request: dict[str, Any]) -> None:
        """Deliver a request to an active session."""

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        """Yield normalized provider events for a session."""

    def canonical_session_id(self, session_id: str) -> str:
        """Return the provider-native session id for a stored session reference."""

    def get_capabilities(self) -> dict[str, Any]:
        """Return provider capabilities such as models and features."""

    def get_session_reference(self, session_id: str) -> dict[str, Any]:
        """Return a durable reference for resuming this session later."""

    def list_active_sessions(self) -> list[dict[str, str]]:
        """Return tracked sessions as session_id, role, and kind before termination."""

    def terminate_session(self, session_id: str) -> None:
        """Terminate a provider session when orchestration no longer needs it."""

    def terminate_all_sessions(self) -> None:
        """Stop in-flight turns and drop tracked provider sessions."""
