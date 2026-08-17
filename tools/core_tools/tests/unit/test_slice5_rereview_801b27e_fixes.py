"""Slice 5 rereview 801b27e: deadline-bounded teardown and lineage-aware PGID survival."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import (
    ProviderLifecycleTimeoutError,
    ProviderSessionTerminationError,
)
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


def _tracked(provider: CursorProvider, tmp_path: Path, *, pgid: int = 4242):
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=pgid, start_time="100", run_id="run-a", owner_id="owner-a")
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


def test_foreign_live_group_member_is_not_this_session_survivor(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id, entry = _tracked(provider, tmp_path)
    entry.group_observed_gone = False
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.FOREIGN,
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
                    "provider_owner_id": "owner-a",
                }
            ],
        )
    assert 5151 not in survival.pids
    assert survival.unresolved is False


def test_failed_termination_unregisters_positively_foreign_live_pgid(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, entry = _tracked(provider, tmp_path)
    del session_id
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
        return_value=GroupLineageState.FOREIGN,
    ):
        provider._terminate_tracked_turn_procs()
    assert 4242 not in provider._tracked_turn_procs


def test_group_observed_gone_does_not_resurrect_reused_pgid(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id, entry = _tracked(provider, tmp_path)
    entry.group_observed_gone = True
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=[5151],
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        survival = provider._surviving_pids_for_session(session_id, [])
        assert 5151 not in survival.pids
        assert provider._tracked_tree_is_live(entry) is False


def test_unresolved_group_enumeration_fails_closed_without_fabricated_pid(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider, tmp_path)
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=None,
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
                    "provider_owner_id": "owner-a",
                }
            ],
        )
    assert 4242 not in survival.pids
    assert survival.unresolved is True


def test_owned_late_child_still_blocks_session_release(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider, tmp_path)
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
        except ProviderSessionTerminationError as exc:
            released = False
            assert 5151 in exc.surviving_pids
    assert released is False
    assert 4242 in provider._tracked_turn_procs


def test_exhausted_teardown_budget_does_not_inflate_inspection_timeout(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider, tmp_path)
    seen: list[float | None] = []

    def record_list(pgid, timeout=None):
        del pgid
        seen.append(timeout)
        return [5151]

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
        "core_tools.provider.cursor.list_process_group_pids",
        side_effect=record_list,
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        try:
            provider.terminate_session(session_id, timeout=0.05)
        except (ProviderSessionTerminationError, ProviderLifecycleTimeoutError):
            pass
    assert seen
    assert all(
        timeout is not None and timeout <= 0.05 + 1e-6 for timeout in seen
    )


def test_duplicate_pgid_is_probed_once_under_shared_deadline(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider, tmp_path)
    calls: list[int] = []

    def record_list(pgid, timeout=None):
        del timeout
        calls.append(pgid)
        return []

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        side_effect=record_list,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "termination_failed",
                    "pgid": 4242,
                    "tree_status": "unresolved",
                    "run_id": "run-a",
                    "provider_owner_id": "owner-a",
                }
            ],
            timeout=0.5,
        )
    assert calls.count(4242) == 1


def test_many_group_members_do_not_each_get_a_fresh_probe_budget(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider, tmp_path)
    members = list(range(6000, 6020))
    budgets: list[float | None] = []
    clock = {"now": 100.0}

    def fake_alive(pid, timeout=None):
        del pid
        budgets.append(timeout)
        clock["now"] += 0.01
        return True

    with patch(
        "core_tools.provider.process_identity.time.monotonic",
        side_effect=lambda: clock["now"],
    ), patch(
        "core_tools.provider.cursor.time.monotonic",
        side_effect=lambda: clock["now"],
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.list_process_group_pids",
        return_value=members,
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        side_effect=fake_alive,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        provider._surviving_pids_for_session(
            session_id,
            [
                {
                    "pid": 4242,
                    "reason": "termination_failed",
                    "pgid": 4242,
                    "tree_status": "unresolved",
                    "run_id": "run-a",
                    "provider_owner_id": "owner-a",
                }
            ],
            timeout=0.2,
        )
    assert budgets
    assert budgets[0] is not None and budgets[0] <= 0.2 + 1e-6
    assert budgets[-1] is not None and budgets[-1] < budgets[0]
    assert all(b is not None and b <= 0.2 + 1e-6 for b in budgets)
