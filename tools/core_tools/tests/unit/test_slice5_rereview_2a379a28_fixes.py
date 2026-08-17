"""Slice 5 rereview 2a379a28: stale FAILED records and mixed zombie/foreign groups."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderSessionTerminationError
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
)
from tests.conftest import tracked_turn_proc


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


def _tracked(provider: CursorProvider, *, pgid: int = 4242):
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(
        pid=pgid, start_time="100", run_id="run-a", owner_id="owner-a"
    )
    proc = MagicMock()
    proc.pid = pgid
    proc.poll.return_value = 1
    provider._tracked_turn_procs[pgid] = tracked_turn_proc(session_id, "planner", pgid)
    entry = provider._tracked_turn_procs[pgid]
    entry.proc = proc
    entry.identity = leader
    entry.pgid = pgid
    entry.member_identities = (leader,)
    entry.owner_id = "owner-a"
    return session_id, entry


def _terminate_session(provider: CursorProvider, session_id: str) -> bool:
    try:
        provider.terminate_session(session_id)
        return True
    except ProviderSessionTerminationError:
        return False


def test_observed_gone_failed_record_does_not_block_release_when_reuse_is_unresolved(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, entry = _tracked(provider)
    entry.group_observed_gone = True
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.GONE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is True
    assert session_id not in provider._sessions
    assert 4242 not in provider._tracked_turn_procs


def test_gone_during_stale_check_still_releases_if_later_lineage_is_unresolved(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    states = iter([ProcessGroupState.GONE, ProcessGroupState.LIVE, ProcessGroupState.LIVE])
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.GONE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        side_effect=lambda *args, **kwargs: next(states, ProcessGroupState.LIVE),
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is True
    assert session_id not in provider._sessions


def test_foreign_stale_reconciliation_survives_later_unresolved_lineage(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    lineages = iter([GroupLineageState.FOREIGN, GroupLineageState.UNRESOLVED])
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.GONE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        side_effect=lambda *args, **kwargs: next(
            lineages, GroupLineageState.UNRESOLVED
        ),
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is True
    assert session_id not in provider._sessions


def test_genuinely_unresolved_owned_tracking_still_blocks_release(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.GONE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is False
    assert 4242 in provider._tracked_turn_procs


def test_owned_zombie_plus_foreign_live_member_keeps_failed_tracking(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    _session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.ZOMBIE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.FOREIGN,
    ):
        provider._terminate_tracked_turn_procs()
    assert 4242 in provider._tracked_turn_procs


def test_terminate_session_does_not_release_owned_zombie_with_foreign_member(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.ZOMBIE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.FOREIGN,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is False
    assert 4242 in provider._tracked_turn_procs


def test_owned_zombie_still_blocks_after_foreign_member_disappears(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.ZOMBIE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[],
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is False


def test_release_succeeds_after_owned_zombie_and_group_are_gone(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.GONE,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.GONE,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is True
    assert 4242 not in provider._tracked_turn_procs


def test_identity_mismatch_plus_foreign_member_may_reconcile(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.IDENTITY_MISMATCH,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.FOREIGN,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        released = _terminate_session(provider, session_id)
    assert released is True
    assert 4242 not in provider._tracked_turn_procs
