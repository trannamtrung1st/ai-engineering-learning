"""Cursor adapter failure classification (session-not-found and action-required)."""

from __future__ import annotations

import re

from core_tools.provider.errors import (
    ProviderActionRequiredError,
    ProviderSessionNotFoundError,
    ProviderTurnError,
)

ACTION_REQUIRED_QUOTA_EXHAUSTED = "quota_exhausted"

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

_QUOTA_EXHAUSTED_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"you(?:['’]re|\s+are)\s+out\s+of\s+usage",
        r"\bout\s+of\s+usage\b",
        r"quota\s+(?:exceeded|exhausted)",
        r"ask\s+your\s+admin\s+to\s+increase\s+your\s+limit",
    )
)


def cursor_message_indicates_session_not_found(message: str) -> bool:
    """Return True when *message* confidently indicates a missing remote session."""

    text = str(message or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SESSION_NOT_FOUND_PATTERNS)


def cursor_message_indicates_quota_exhausted(message: str) -> bool:
    """Return True when *message* confidently indicates account/provider quota exhaustion."""

    text = str(message or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _QUOTA_EXHAUSTED_PATTERNS)


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


def classify_cursor_action_required(
    message: str,
    *,
    session_id: str | None = None,
) -> ProviderActionRequiredError | None:
    """Map a Cursor transport message to a typed action-required provider error."""

    if not cursor_message_indicates_quota_exhausted(message):
        return None
    return ProviderActionRequiredError(
        message,
        reason=ACTION_REQUIRED_QUOTA_EXHAUSTED,
        session_id=session_id,
    )


def classify_cursor_failure(
    message: str,
    *,
    provider: str = "cursor",
    session_id: str | None = None,
) -> ProviderSessionNotFoundError | ProviderActionRequiredError | None:
    """Classify a Cursor failure message into a typed provider error when possible."""

    session_failure = classify_cursor_session_failure(
        message,
        provider=provider,
        session_id=session_id,
    )
    if session_failure is not None:
        return session_failure
    return classify_cursor_action_required(message, session_id=session_id)


def reclassify_provider_turn_error(
    exc: ProviderTurnError,
    *,
    provider: str = "cursor",
    session_id: str | None = None,
) -> ProviderTurnError:
    """Re-raise *exc* as a more specific provider error when classification matches."""

    if isinstance(exc, (ProviderSessionNotFoundError, ProviderActionRequiredError)):
        return exc
    resolved_session_id = session_id or exc.session_id
    classified = classify_cursor_failure(
        str(exc),
        provider=provider,
        session_id=resolved_session_id,
    )
    if classified is not None:
        return classified
    return exc


__all__ = [
    "ACTION_REQUIRED_QUOTA_EXHAUSTED",
    "classify_cursor_action_required",
    "classify_cursor_failure",
    "classify_cursor_session_failure",
    "cursor_message_indicates_quota_exhausted",
    "cursor_message_indicates_session_not_found",
    "reclassify_provider_turn_error",
]
