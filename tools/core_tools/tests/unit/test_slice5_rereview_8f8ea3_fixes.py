"""Slice 5 rereview 8f8ea3: fail-closed session release after unexpected janitor death."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderLifecycleTimeoutError, ProviderSessionTerminationError
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
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


def test_failed_termination_does_not_unregister_when_tree_probe_says_dead(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.return_value = 1
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.proc = proc
    entry.identity = leader
    entry.pgid = 4242
    entry.member_identities = (leader,)

    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ):
        records = provider._terminate_tracked_turn_procs()

    assert 4242 in provider._tracked_turn_procs
    assert records[0]["reason"] == "termination_failed"


def test_surviving_pids_include_live_group_members_not_in_historical_identities(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.pgid = 4242
    entry.member_identities = (leader,)
    entry.proc = None

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=lambda pid, timeout=None: pid == 5151,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        survival = provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "termination_failed",
                    "pgid": 4242,
                    "tree_status": "unresolved",
                    "run_id": "run-a",
                }
            ],
        )
    assert 5151 in survival.pids


def test_surviving_pids_include_live_group_members_after_terminated_record(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=lambda pid, timeout=None: pid == 5151,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        survival = provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "terminated",
                    "pgid": 4242,
                    "run_id": "run-a",
                    "provider_owner_id": "owner-a",
                }
            ],
        )
    assert 5151 in survival.pids


def test_surviving_pids_include_owned_members_even_when_group_was_observed_gone(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=lambda pid, timeout=None: pid == 5151,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        survival = provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "termination_failed",
                    "pgid": 4242,
                    "tree_status": "unresolved",
                    "run_id": "run-a",
                    "group_observed_gone": True,
                }
            ],
        )
    assert 5151 in survival.pids


def test_surviving_pids_include_live_group_members_after_terminated_record(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=lambda pid, timeout=None: pid == 5151,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        survival = provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "terminated",
                    "pgid": 4242,
                    "run_id": "run-a",
                    "provider_owner_id": "owner-a",
                }
            ],
        )
    assert 5151 in survival.pids


def test_surviving_pids_include_owned_members_even_when_group_was_observed_gone(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=lambda pid, timeout=None: pid == 5151,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        survival = provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "termination_failed",
                    "pgid": 4242,
                    "tree_status": "unresolved",
                    "run_id": "run-a",
                    "group_observed_gone": True,
                }
            ],
        )
    assert 5151 in survival.pids


def test_terminate_session_does_not_release_after_abort_turn_timeout(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
        side_effect=ProviderLifecycleTimeoutError(
            "surviving agent processes [5151]",
            session_id=session_id,
        ),
    ):
        try:
            provider.terminate_session(session_id, timeout=2.0)
            released = True
        except (ProviderSessionTerminationError, ProviderLifecycleTimeoutError):
            released = False
    assert released is False
    assert session_id in provider._sessions


def test_terminate_session_fails_closed_when_group_member_survives(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.return_value = 1
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.proc = proc
    entry.identity = leader
    entry.pgid = 4242
    entry.member_identities = (leader,)
    entry.owner_id = "owner-a"

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
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=lambda pid, timeout=None: pid == 5151,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        try:
            provider.terminate_session(session_id)
            released = True
        except ProviderSessionTerminationError:
            released = False
    assert released is False
    assert session_id in provider._sessions or provider.canonical_session_id(
        session_id
    ) in provider._sessions
    assert 4242 in provider._tracked_turn_procs
