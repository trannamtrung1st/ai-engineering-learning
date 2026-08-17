"""Slice 5 rereview c442ae0: pending→durable tracking must keep owner metadata."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_identity import ProcessIdentity


def _provider(tmp_path: Path) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent),
        skip_probe=True,
    )


def test_pending_to_durable_migration_preserves_tracking_metadata(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    pending_id = provider.start_primary_session("planner", {"goal": "x"})
    proc = MagicMock()
    proc.pid = 4242
    original = _TrackedTurnProc(
        session_id=pending_id,
        role="planner",
        proc=proc,
        identity=None,
        pgid=4242,
        member_identities=None,
        group_observed_gone=False,
        generation=99,
        owner_id="owner-token-abc",
    )
    provider._tracked_turn_procs[4242] = original
    snapshot = {field.name: getattr(original, field.name) for field in fields(_TrackedTurnProc)}

    provider._maybe_migrate_session(pending_id, "chat-planner-1")

    tracked = provider._tracked_turn_procs[4242]
    assert tracked.session_id == "chat-planner-1"
    for name, value in snapshot.items():
        if name == "session_id":
            continue
        assert getattr(tracked, name) is value or getattr(tracked, name) == value

    synthetic = ProcessIdentity(pid=4242, start_time="100")
    with patch(
        "core_tools.provider.cursor.read_process_identity",
        return_value=synthetic,
    ), patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        return_value=None,
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ):
        provider._enrich_tracked_turn_proc(proc, timeout=0.05)

    assert tracked.identity is not None
    assert tracked.identity.owner_id == "owner-token-abc"
    record = provider._termination_record_for_tracked_proc(tracked)
    assert record["provider_owner_id"] == "owner-token-abc"
