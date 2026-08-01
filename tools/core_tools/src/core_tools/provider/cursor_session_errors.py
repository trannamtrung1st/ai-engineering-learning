"""Cursor adapter session-not-found classification (proposal §12)."""

from __future__ import annotations

import re

from core_tools.provider.errors import (
    ProviderSessionNotFoundError,
    ProviderTurnError,
)

_SESSION_NOT_FOUND_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"session\s+not\s+found",
        r"unknown\s+session(?:\s+id)?",
        r"invalid\s+session(?:\s+id)?",
        r"could\s+not\s+(?:find|resume)\s+session",
        r"no\s+such\s+session",
        r"session\s+does\s+not\s+exist",
        r"session\s+id\s+.*\s+not\s+found",
        r"chat\s+session\s+not\s+found",
        r"resume\s+session\s+not\s+found",
    )
)


def cursor_message_indicates_session_not_found(message: str) -> bool:
    """Return True when *message* confidently indicates a missing remote session."""

    text = str(message or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SESSION_NOT_FOUND_PATTERNS)


def classify_cursor_session_failure(
    message: str,
    *,
    provider: str = "cursor",
    session_id: str | None = None,
) -> ProviderSessionNotFoundError | None:
    """Map a Cursor transport message to a typed missing-session error."""

    if not cursor_message_indicates_session_not_found(message):
        return None
    return ProviderSessionNotFoundError(
        message,
        provider=provider,
        session_id=session_id,
    )


def reclassify_provider_turn_error(
    exc: ProviderTurnError,
    *,
    provider: str = "cursor",
    session_id: str | None = None,
) -> ProviderTurnError | ProviderSessionNotFoundError:
    """Re-raise *exc* as ProviderSessionNotFoundError when classification matches."""

    resolved_session_id = session_id or exc.session_id
    classified = classify_cursor_session_failure(
        str(exc),
        provider=provider,
        session_id=resolved_session_id,
    )
    if classified is not None:
        return classified
    return exc


__all__ = [
    "classify_cursor_session_failure",
    "cursor_message_indicates_session_not_found",
    "reclassify_provider_turn_error",
]
