"""Cursor transport chat resume arguments."""

from __future__ import annotations

from pathlib import Path

from todos_tool.cursor_transport import build_agent_args, SessionResult


def test_build_agent_args_includes_resume() -> None:
    args = build_agent_args(
        workspace=Path("/tmp/ws"),
        prompt="hello",
        phase="work",
        model=None,
        stream_flags=["--output-format", "stream-json"],
        resume_chat_id="chat-123",
    )
    assert "--resume" in args
    assert "chat-123" in args


def test_session_result_has_session_id() -> None:
    result = SessionResult(exit_code=0, session_id="chat-abc")
    assert result.session_id == "chat-abc"
