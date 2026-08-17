"""Slice 5 rereview 3452a251: zombie-only groups are not GONE; abort unresolved message."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import (
    ProviderLifecycleTimeoutError,
    ProviderSessionTerminationError,
)
from core_tools.provider.process_cleanup import PidInspectState, ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    ProcessIdentity,
    TerminateIdentityResult,
    current_process_group_lineage,
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


def test_zombie_only_group_lineage_is_not_gone() -> None:
    with patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=None,
    ), patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        return_value=PidInspectState.ZOMBIE,
    ):
        lineage = current_process_group_lineage(
            4242, expected_run_id="run-a", expected_owner_id="owner-a"
        )
    assert lineage is not GroupLineageState.GONE
    assert lineage is GroupLineageState.UNRESOLVED


def test_failed_termination_keeps_tracking_for_zombie_only_live_group(
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
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=None,
    ), patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        return_value=PidInspectState.ZOMBIE,
    ):
        provider._terminate_tracked_turn_procs()
    assert 4242 in provider._tracked_turn_procs
    assert provider._tracked_turn_procs[4242].group_observed_gone is False


def test_terminate_session_does_not_release_zombie_only_group(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=None,
    ), patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        return_value=PidInspectState.ZOMBIE,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        with pytest.raises(ProviderSessionTerminationError) as exc_info:
            provider.terminate_session(session_id)
    assert session_id in provider._sessions or provider.canonical_session_id(
        session_id
    ) in provider._sessions
    assert 4242 in provider._tracked_turn_procs
    assert exc_info.value.surviving_pids == ()
    assert "unresolved provider process ownership" in str(exc_info.value)


def test_failed_tracking_may_drop_after_zombie_group_is_gone(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    _session_id, _entry = _tracked(provider)
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.GONE,
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.GONE,
    ), patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[],
    ):
        provider._terminate_tracked_turn_procs()
    assert 4242 not in provider._tracked_turn_procs


def test_abort_turn_unresolved_ownership_does_not_claim_empty_survivors(
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
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=None,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=None,
    ):
        with pytest.raises(ProviderLifecycleTimeoutError) as exc_info:
            provider.abort_turn(session_id, timeout=0.5)
    message = str(exc_info.value)
    assert "unresolved provider process ownership" in message
    assert "surviving agent processes []" not in message
