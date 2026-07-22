"""Backward-compatible re-exports from cursor_transport."""

from todos_tool.cursor_transport import (
    AgentStartedCallback,
    CursorClient,
    CursorTransport,
    PhaseName,
    PROMPT_FILE_ENV,
    SessionResult,
    active_session_count,
    build_agent_args,
    build_bootstrap_prompt,
    default_stream_flags,
    probe_stream_flags,
    resolve_agent_bin,
)

__all__ = [
    "AgentStartedCallback",
    "CursorClient",
    "CursorTransport",
    "PhaseName",
    "PROMPT_FILE_ENV",
    "SessionResult",
    "active_session_count",
    "build_agent_args",
    "build_bootstrap_prompt",
    "default_stream_flags",
    "probe_stream_flags",
    "resolve_agent_bin",
]
