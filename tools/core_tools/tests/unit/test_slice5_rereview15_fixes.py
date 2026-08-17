"""Slice 5 fifteenth re-review regressions (S5-RR15-001 and S5-RR15-002)."""

from __future__ import annotations

import errno
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    inspect_pid_liveness,
    is_pid_alive,
    list_process_group_pids,
    process_group_state,
)
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    _signal_identity,
    drain_owned_process_group,
    inspect_process_identity,
    process_identity_is_live,
)


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


def test_inspect_process_identity_unreadable_stat_is_unverifiable_not_dead() -> None:
    identity = ProcessIdentity(pid=11, start_time="999")
    with patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        return_value=PidInspectState.LIVE,
    ):
        with patch(
            "core_tools.provider.process_identity.read_process_identity",
            return_value=None,
        ):
            assert inspect_process_identity(identity) is IdentityInspectState.UNVERIFIABLE
            assert process_identity_is_live(identity) is True


def test_inspect_process_identity_gone_and_mismatch() -> None:
    identity = ProcessIdentity(pid=11, start_time="100")
    with patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        return_value=PidInspectState.GONE,
    ):
        assert inspect_process_identity(identity) is IdentityInspectState.GONE
        assert process_identity_is_live(identity) is False

    reused = ProcessIdentity(pid=11, start_time="200")
    with patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        return_value=PidInspectState.LIVE,
    ):
        with patch(
            "core_tools.provider.process_identity.read_process_identity",
            return_value=reused,
        ):
            assert inspect_process_identity(identity) is IdentityInspectState.IDENTITY_MISMATCH
            assert process_identity_is_live(identity) is False


def test_signal_identity_does_not_succeed_when_unreadable() -> None:
    identity = ProcessIdentity(pid=11, start_time="999")
    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ):
        with patch("core_tools.provider.process_identity.os.kill") as kill:
            assert _signal_identity(identity, signal.SIGTERM) is False
    kill.assert_not_called()


def test_no_pgid_drain_fails_closed_when_identity_unreadable() -> None:
    identity = ProcessIdentity(pid=11, start_time="999")
    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ):
        assert drain_owned_process_group(pgid=None, leader_identity=identity) is False


def test_cursor_does_not_prune_unreadable_live_tree(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    identity = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=identity,
        pgid=4242,
        member_identities=(identity,),
    )

    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ):
        provider._prune_dead_tracked_pids_for_session(session_id)
        assert 4242 in provider._tracked_turn_procs
        assert provider._session_has_surviving_pids(session_id) is True


def test_darwin_kill_eperm_is_not_dead(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)

    def deny(_pid: int, _sig: int) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    with patch("core_tools.provider.process_cleanup.os.kill", side_effect=deny):
        assert inspect_pid_liveness(5151) is PidInspectState.UNVERIFIABLE
        assert is_pid_alive(5151) is True


def test_darwin_kill_esrch_is_gone(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)

    def missing(_pid: int, _sig: int) -> None:
        raise OSError(errno.ESRCH, "No such process")

    with patch("core_tools.provider.process_cleanup.os.kill", side_effect=missing):
        assert inspect_pid_liveness(5151) is PidInspectState.GONE
        assert is_pid_alive(5151) is False


def test_darwin_ps_nonzero_empty_output_is_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    result = MagicMock(returncode=1, stdout="", stderr="")
    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        return_value=result,
    ):
        assert list_process_group_pids(99) is None
        assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE


def test_darwin_successful_query_with_zero_members_is_gone(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    result = MagicMock(returncode=0, stdout="1 1 S\n2 1 S\n")
    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        return_value=result,
    ):
        with patch(
            "core_tools.provider.process_cleanup.inspect_pid_liveness",
            return_value=PidInspectState.LIVE,
        ):
            assert list_process_group_pids(99) == []
            assert process_group_state(99) is ProcessGroupState.GONE


def test_darwin_eperm_group_member_makes_group_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    result = MagicMock(returncode=0, stdout="5151 99 S\n")

    def eperm(_pid: int, _sig: int) -> None:
        raise PermissionError("Operation not permitted")

    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        return_value=result,
    ):
        with patch(
            "core_tools.provider.process_cleanup.os.kill",
            side_effect=eperm,
        ):
            assert list_process_group_pids(99) == [5151]
            assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE
            assert drain_owned_process_group(
                pgid=99,
                leader_identity=ProcessIdentity(pid=5151, start_time="100"),
            ) is False
