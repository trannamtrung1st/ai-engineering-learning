"""Slice 5 rereview ee5de8e: pin first Cursor durable ID (TDP-S5EE5D-08)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderSessionMismatchError
from tests.conftest import tracked_turn_proc


def _cursor(
    tmp_path: Path,
    stream_lines: list[str],
) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")

    def fake_runner(argv: list[str], cwd: Path):
        yield from stream_lines

    return CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )


def _session_lines(*session_ids: str, include_result: bool = True) -> list[str]:
    lines: list[str] = []
    for session_id in session_ids:
        lines.append(
            json.dumps({"type": "system", "subtype": "init", "session_id": session_id})
        )
    if include_result:
        final_id = session_ids[-1]
        lines.append(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "session_id": final_id,
                    "is_error": False,
                    "result": "ok",
                }
            )
        )
    return lines


def test_second_durable_identity_on_new_turn_is_rejected(tmp_path: Path) -> None:
    provider = _cursor(tmp_path, _session_lines("cursor-d1", "cursor-d2"))
    pending = provider.start_primary_session("planner", {"goal": "build"})
    provider._tracked_turn_procs[101] = tracked_turn_proc(pending, "planner", 101)

    with pytest.raises(ProviderSessionMismatchError):
        list(provider.stream_events(pending))

    assert provider.canonical_session_id(pending) == "cursor-d1"
    assert "cursor-d1" not in provider._session_aliases
    assert provider._session_aliases.get(pending) == "cursor-d1"
    assert pending not in provider._sessions
    assert "cursor-d1" in provider._sessions
    assert "cursor-d2" not in provider._sessions
    assert provider._tracked_turn_procs[101].session_id == "cursor-d1"
    provider._tracked_turn_procs.pop(101, None)

    provider.terminate_session(pending)
    assert "cursor-d1" not in {s["session_id"] for s in provider.list_active_sessions()}


def test_repeated_first_durable_identity_continues_to_succeed(tmp_path: Path) -> None:
    provider = _cursor(tmp_path, _session_lines("cursor-d1", "cursor-d1"))
    pending = provider.start_primary_session("planner", {"goal": "build"})
    events = list(provider.stream_events(pending))
    assert events[-1]["type"] == "done"
    assert provider.canonical_session_id(pending) == "cursor-d1"
    assert provider.canonical_session_id("cursor-d1") == "cursor-d1"
    provider.terminate_session("cursor-d1")
    assert provider.list_active_sessions() == []


def test_canonical_session_id_resolves_alias_chains_without_cycles(
    tmp_path: Path,
) -> None:
    provider = _cursor(tmp_path, [])
    provider._session_aliases["pending-p"] = "d1"
    provider._session_aliases["d1"] = "d2"
    assert provider.canonical_session_id("pending-p") == "d2"
    provider._session_aliases["loop-a"] = "loop-b"
    provider._session_aliases["loop-b"] = "loop-a"
    assert provider.canonical_session_id("loop-a") in {"loop-a", "loop-b"}
