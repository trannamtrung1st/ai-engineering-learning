"""Cursor queued-turn lifecycle regressions (S5-RR9-003)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError


def test_initial_primary_turn_is_marked_queued(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )

    session_id = provider.start_primary_session("planner", {"goal": "x"})
    session = provider._sessions[session_id]

    assert session.pending_argv is not None
    assert session.turn_queued is True
    assert session.turn_running is False


def test_resume_before_initial_stream_is_rejected(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    with pytest.raises(ProviderTurnError, match="already queued"):
        provider.resume_primary_session(
            session_id,
            {"request": "resume"},
            role="planner",
        )


def test_reviewer_send_before_initial_stream_is_rejected(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_reviewer_session({"loop_id": "review-01"})

    with pytest.raises(ProviderTurnError, match="already queued"):
        provider.send(session_id, {"action": "initial_review", "loop_id": "review-01"})


def test_abort_queued_turn_clears_state_and_allows_later_resume(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider.abort_turn(session_id)
    session = provider._sessions[session_id]

    assert session.pending_argv is None
    assert session.turn_queued is False

    provider.resume_primary_session(
        session_id,
        {"request": "resume"},
        role="planner",
    )
    assert session.pending_argv is not None
    assert session.turn_queued is True


def test_concurrent_durable_resume_rejects_second_queued_turn(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    durable_id = "chat-planner-shared"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def resume_once() -> None:
        try:
            barrier.wait(timeout=1.0)
            provider.resume_primary_session(
                durable_id,
                {"request": "resume"},
                role="planner",
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=resume_once),
        threading.Thread(target=resume_once),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    turn_errors = [exc for exc in errors if isinstance(exc, ProviderTurnError)]
    assert len(turn_errors) == 1
    assert "already queued" in str(turn_errors[0])
    session = provider._sessions[durable_id]
    assert session.pending_argv is not None


def test_reviewer_first_stream_omits_resume_for_pending_session(tmp_path: Path) -> None:
    captured_argv: list[list[str]] = []

    def fake_runner(argv: list[str], cwd: Path):
        captured_argv.append(argv)
        yield json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-reviewer-1",
            }
        )
        yield json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-reviewer-1",
                "is_error": False,
                "result": "reviewed",
            }
        )

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {"provider": {"name": "cursor"}},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )

    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    list(provider.stream_events(session_id))

    assert len(captured_argv) == 1
    assert "--resume" not in captured_argv[0]
    assert provider.canonical_session_id(session_id) == "chat-reviewer-1"
