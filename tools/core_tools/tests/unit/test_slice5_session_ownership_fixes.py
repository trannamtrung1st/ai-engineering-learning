"""Slice 5 session-ownership and lock/teardown regressions (TDP-S5B9F1-01/03/06)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderSessionError
from tests.conftest import tracked_turn_proc


def _provider(tmp_path: Path) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )


def test_duplicate_durable_migration_fails_closed_and_preserves_owner(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_a = provider.start_primary_session("planner", {"goal": "a"})
    session_b = provider.start_primary_session("reviewer", {"goal": "b"})
    owner = provider._sessions[session_a]
    other = provider._sessions[session_b]
    provider._tracked_turn_procs[101] = tracked_turn_proc(session_a, "planner", 101)
    provider._tracked_turn_procs[202] = tracked_turn_proc(session_b, "reviewer", 202)
    durable = "cursor-durable-1"

    first = provider._maybe_migrate_session(session_a, durable)
    aliases_after_first = dict(provider._session_aliases)
    tracked_after_first = {
        pid: entry.session_id for pid, entry in provider._tracked_turn_procs.items()
    }

    with pytest.raises(ProviderSessionError, match="already owned"):
        provider._maybe_migrate_session(session_b, durable)

    assert first == durable
    assert provider._sessions[durable] is owner
    assert provider._sessions[session_b] is other
    assert session_b in provider._sessions
    assert provider._session_aliases == aliases_after_first
    assert provider._session_aliases.get(session_b) != durable
    assert {
        pid: entry.session_id for pid, entry in provider._tracked_turn_procs.items()
    } == tracked_after_first
    assert provider._tracked_turn_procs[101].session_id == durable
    assert provider._tracked_turn_procs[202].session_id == session_b


def test_duplicate_durable_migration_allows_idempotent_same_session(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_a = provider.start_primary_session("planner", {"goal": "a"})
    durable = "cursor-durable-1"
    first = provider._maybe_migrate_session(session_a, durable)
    again = provider._maybe_migrate_session(durable, durable)
    via_alias = provider._maybe_migrate_session(session_a, durable)
    assert first == durable
    assert again == durable
    assert via_alias == durable
    assert provider._sessions[durable] is not None


def test_stream_events_releases_session_lock_before_yield(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "a"})
    session = provider._sessions[session_id]
    with session.condition:
        session.pending_argv = None
        session.turn_queued = False
        session.pending_events.append({"type": "assistant", "text": "hi"})

    gen = provider.stream_events(session_id)
    event = next(gen)
    assert event["type"] == "assistant"

    finished = threading.Event()

    def abort() -> None:
        provider.abort_turn(session_id)
        finished.set()

    thread = threading.Thread(target=abort)
    thread.start()
    thread.join(timeout=0.4)
    assert thread.is_alive() is False
    assert finished.is_set() is True


def test_abort_after_consuming_streamed_event_does_not_deadlock(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "a"})
    session = provider._sessions[session_id]
    with session.condition:
        session.pending_argv = None
        session.turn_queued = False
        session.pending_events.append({"type": "assistant", "text": "hi"})

    gen = provider.stream_events(session_id)
    assert next(gen)["text"] == "hi"
    started = time.monotonic()
    provider.abort_turn(session_id)
    assert time.monotonic() - started < 0.4


def test_terminate_all_sessions_restores_shutting_down_after_failure(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    provider.start_primary_session("planner", {"goal": "a"})
    with patch.object(
        provider,
        "_abort_inflight_sessions",
        side_effect=RuntimeError("teardown boom"),
    ):
        with pytest.raises(RuntimeError, match="teardown boom"):
            provider.terminate_all_sessions()
    assert provider._shutting_down is False

    provider.terminate_all_sessions()
    assert provider._shutting_down is False
    assert provider.list_active_sessions() == []
