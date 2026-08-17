"""Slice 5 thirteenth re-review regressions (S5-RR13-001 through S5-RR13-005)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.errors import ProviderSessionTerminationError
from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    is_pid_alive,
    list_process_group_pids,
)
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
    _pidfd_supported,
    _signal_identity,
    _terminate_bound_process,
    drain_owned_process_group,
    process_identity_from_termination_record,
    terminate_verified_process_identity,
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


def _linux_stat_text(pid: int, state: str, pgid: int, start_time: str = "999") -> str:
    fields = [state, "1", str(pgid)] + ["0"] * 16 + [start_time]
    return f"{pid} (cmd) {' '.join(fields)}\n"


# --- S5-RR13-002: never seed ownership from current PGID occupants ---


def test_terminate_bound_process_fails_closed_when_dead_leader_has_no_member_snapshot() -> None:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = 1
    original = ProcessIdentity(pid=4242, start_time="100")
    reused = ProcessIdentity(pid=5151, start_time="200")

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            return_value=[reused],
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                side_effect=lambda identity, timeout=None: identity.pid == 5151,
            ):
                with patch(
                    "core_tools.provider.process_identity.read_process_group_id",
                    return_value=4242,
                ):
                    with patch(
                        "core_tools.provider.process_identity._wait_identities_dead",
                        return_value=True,
                    ):
                        with patch(
                            "core_tools.provider.process_identity._signal_identity",
                        ) as signal_identity:
                            result = _terminate_bound_process(
                                original,
                                proc,
                                pgid=4242,
                                member_identities=None,
                            )

    assert result == TerminateIdentityResult.FAILED
    signal_identity.assert_not_called()


def test_terminate_bound_process_fails_closed_when_identity_is_missing_and_leader_dead() -> None:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = 1
    reused = ProcessIdentity(pid=5151, start_time="200")

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            return_value=[reused],
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                return_value=True,
            ):
                with patch(
                    "core_tools.provider.process_identity.read_process_group_id",
                    return_value=4242,
                ):
                    with patch(
                        "core_tools.provider.process_identity._wait_identities_dead",
                        return_value=True,
                    ):
                        with patch(
                            "core_tools.provider.process_identity._signal_identity",
                        ) as signal_identity:
                            result = _terminate_bound_process(
                                None,
                                proc,
                                pgid=4242,
                                member_identities=None,
                            )

    assert result == TerminateIdentityResult.FAILED
    signal_identity.assert_not_called()


def test_drain_adopts_new_members_when_original_live_anchor_still_owns_group() -> None:
    leader = ProcessIdentity(pid=4242, start_time="leader")
    child = ProcessIdentity(pid=5151, start_time="child")
    rounds = {"n": 0}
    signaled: list[int] = []

    def fake_current(pgid: int, *, run_id: str | None = None, timeout: float | None = None) -> list[ProcessIdentity]:
        rounds["n"] += 1
        if rounds["n"] == 1:
            return [leader]
        return [leader, child]

    def fake_signal(identity: ProcessIdentity, sig: int, *, timeout: float | None = None) -> bool:
        signaled.append(identity.pid)
        return True

    def fake_state(pgid: int, *, timeout: float | None = None) -> ProcessGroupState:
        if child.pid in signaled:
            return ProcessGroupState.GONE
        return ProcessGroupState.LIVE

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        side_effect=fake_state,
    ):
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            side_effect=fake_current,
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                return_value=True,
            ):
                with patch(
                    "core_tools.provider.process_identity.read_process_group_id",
                    return_value=4242,
                ):
                    with patch(
                        "core_tools.provider.process_identity._signal_identity",
                        side_effect=fake_signal,
                    ):
                        with patch(
                            "core_tools.provider.process_identity._wait_identities_dead",
                            return_value=True,
                        ):
                            result = drain_owned_process_group(
                                pgid=4242,
                                leader_identity=leader,
                                known_identities=[leader],
                            )

    assert result is True
    assert 5151 in signaled


# --- S5-RR13-001: tree-aware provider bookkeeping ---


def test_failed_tree_drain_keeps_tracking_when_leader_is_dead(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    child = ProcessIdentity(pid=5151, start_time="200", run_id="run-a")
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = 1
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=proc,
        identity=leader,
        pgid=4242,
        member_identities=(leader, child),
    )

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=False):
        with patch(
            "core_tools.provider.cursor.inspect_process_identity",
            side_effect=lambda identity, timeout=None: (
                IdentityInspectState.LIVE_MATCH
                if identity.pid == 5151
                else IdentityInspectState.GONE
            ),
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                side_effect=lambda identity, timeout=None: identity.pid == 5151,
            ):
                with patch(
                    "core_tools.provider.cursor.terminate_verified_process_identity",
                    return_value=TerminateIdentityResult.FAILED,
                ):
                    records = provider._terminate_tracked_turn_procs()

    assert 4242 in provider._tracked_turn_procs
    assert records[0]["reason"] == "termination_failed"
    assert records[0]["pgid"] == 4242
    assert records[0]["tree_status"] == "unresolved"
    assert records[0]["member_pids"] == [4242, 5151]
    assert process_identity_from_termination_record(records[0]) == leader


def test_prune_and_survival_detect_descendant_only_tree(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    child = ProcessIdentity(pid=5151, start_time="200")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader, child),
    )

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=False):
        with patch(
            "core_tools.provider.process_identity._identity_still_alive",
            side_effect=lambda identity, timeout=None: identity.pid == 5151,
        ):
            provider._prune_dead_tracked_pids_for_session(session_id)
            assert 4242 in provider._tracked_turn_procs
            assert provider._session_has_surviving_pids(session_id) is True
            surviving = provider._surviving_pids_for_session(
                session_id,
                [
                    {
                        "pid": 4242,
                        "reason": "termination_failed",
                        "tree_status": "unresolved",
                        "member_pids": [4242, 5151],
                    }
                ],
            )
            assert 5151 in surviving


def test_terminate_session_raises_when_leader_dead_and_tree_unresolved(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    child = ProcessIdentity(pid=5151, start_time="200")
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = 1
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=proc,
        identity=leader,
        pgid=4242,
        member_identities=(leader, child),
    )

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=False):
        with patch(
            "core_tools.provider.cursor.inspect_process_identity",
            side_effect=lambda identity, timeout=None: (
                IdentityInspectState.LIVE_MATCH
                if identity.pid == 5151
                else IdentityInspectState.GONE
            ),
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                side_effect=lambda identity, timeout=None: identity.pid == 5151,
            ):
                with patch(
                    "core_tools.provider.cursor.terminate_verified_process_identity",
                    return_value=TerminateIdentityResult.FAILED,
                ):
                    with pytest.raises(ProviderSessionTerminationError) as exc_info:
                        provider.terminate_session(session_id)

    assert session_id in provider._sessions
    assert 4242 in provider._tracked_turn_procs
    assert 5151 in exc_info.value.surviving_pids


def test_session_migration_preserves_tree_ownership_metadata(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    pending_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    child = ProcessIdentity(pid=5151, start_time="200")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=pending_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader, child),
    )

    provider._maybe_migrate_session(pending_id, "chat-planner-1")

    tracked = provider._tracked_turn_procs[4242]
    assert tracked.session_id == "chat-planner-1"
    assert tracked.pgid == 4242
    assert tracked.member_identities == (leader, child)


# --- S5-RR13-003: fail closed without process-instance-safe signaling ---


def test_signal_identity_does_not_raw_kill_without_pidfd() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100")

    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.process_identity.inspect_process_identity",
            return_value=IdentityInspectState.LIVE_MATCH,
        ):
            with patch("core_tools.provider.process_identity.os.kill") as kill:
                result = _signal_identity(identity, signal.SIGTERM)

    assert result is False
    kill.assert_not_called()


def test_signal_identity_pid_reuse_before_signal_does_not_kill_replacement() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100")
    calls = {"n": 0}

    def fake_alive(_identity: ProcessIdentity) -> bool:
        calls["n"] += 1
        return calls["n"] == 1

    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.process_identity.inspect_process_identity",
            return_value=IdentityInspectState.LIVE_MATCH,
        ):
            with patch("core_tools.provider.process_identity.os.kill") as kill:
                result = _signal_identity(identity, signal.SIGKILL)

    assert result is False
    kill.assert_not_called()


def test_terminate_verified_identity_fails_closed_without_pidfd_or_bound_handle() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100")

    with patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ):
        with patch(
            "core_tools.provider.process_identity._pidfd_supported",
            return_value=False,
        ):
            with patch(
                "core_tools.provider.process_identity.drain_owned_process_group",
            ) as drain:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.FAILED
    drain.assert_not_called()


def test_darwin_identity_cleanup_fails_closed_without_raw_kill(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    identity = ProcessIdentity(pid=4242, start_time="Wed Aug 13 00:00:00 2026")

    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.process_identity.inspect_process_identity",
            return_value=IdentityInspectState.LIVE_MATCH,
        ):
            with patch("core_tools.provider.process_identity.os.kill") as kill:
                assert _signal_identity(identity, signal.SIGTERM) is False
    kill.assert_not_called()


# --- S5-RR13-004: child must appear after the first membership snapshot ---


def test_drain_discovers_or_fails_when_child_forks_after_first_snapshot() -> None:
    leader = ProcessIdentity(pid=4242, start_time="leader")
    late_child = ProcessIdentity(pid=5151, start_time="late")
    rounds = {"n": 0}
    signaled: list[int] = []
    snapshots: list[list[int]] = []

    def fake_current(pgid: int, *, run_id: str | None = None, timeout: float | None = None) -> list[ProcessIdentity]:
        rounds["n"] += 1
        if rounds["n"] == 1:
            members = [leader]
        else:
            members = [leader, late_child]
        snapshots.append([identity.pid for identity in members])
        return members

    def fake_signal(identity: ProcessIdentity, sig: int, *, timeout: float | None = None) -> bool:
        signaled.append(identity.pid)
        return True

    def fake_state(pgid: int, *, timeout: float | None = None) -> ProcessGroupState:
        if late_child.pid in signaled:
            return ProcessGroupState.GONE
        return ProcessGroupState.LIVE

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        side_effect=fake_state,
    ):
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            side_effect=fake_current,
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                return_value=True,
            ):
                with patch(
                    "core_tools.provider.process_identity.read_process_group_id",
                    return_value=4242,
                ):
                    with patch(
                        "core_tools.provider.process_identity._signal_identity",
                        side_effect=fake_signal,
                    ):
                        with patch(
                            "core_tools.provider.process_identity._wait_identities_dead",
                            return_value=True,
                        ):
                            result = drain_owned_process_group(
                                pgid=4242,
                                leader_identity=leader,
                                known_identities=[leader],
                            )

    assert snapshots[0] == [4242]
    assert 5151 in snapshots[1]
    assert result is True
    assert 5151 in signaled


def test_drain_never_succeeds_while_bounded_late_forks_keep_appearing() -> None:
    leader = ProcessIdentity(pid=4242, start_time="leader")
    live_late: set[int] = set()

    def fake_current(pgid: int, *, run_id: str | None = None, timeout: float | None = None) -> list[ProcessIdentity]:
        child = ProcessIdentity(pid=5000 + len(live_late) + 1, start_time="late")
        live_late.add(child.pid)
        return [leader, child]

    def fake_signal(identity: ProcessIdentity, sig: int, *, timeout: float | None = None) -> bool:
        live_late.discard(identity.pid)
        return True

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            side_effect=fake_current,
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                return_value=True,
            ):
                with patch(
                    "core_tools.provider.process_identity.read_process_group_id",
                    return_value=4242,
                ):
                    with patch(
                        "core_tools.provider.process_identity._signal_identity",
                        side_effect=fake_signal,
                    ):
                        with patch(
                            "core_tools.provider.process_identity._wait_identities_dead",
                            return_value=True,
                        ):
                            result = drain_owned_process_group(
                                pgid=4242,
                                leader_identity=leader,
                                known_identities=[leader],
                            )

    assert result is False


# --- S5-RR13-005: Linux /proc enumeration must not spawn ps per PID ---


def test_linux_group_enumeration_reads_proc_stat_without_ps(
    tmp_path: Path, monkeypatch
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "10").mkdir()
    (proc_root / "10" / "stat").write_text(_linux_stat_text(10, "S", 99), encoding="utf-8")
    (proc_root / "11").mkdir()
    (proc_root / "11" / "stat").write_text(_linux_stat_text(11, "S", 99), encoding="utf-8")
    (proc_root / "12").mkdir()
    (proc_root / "12" / "stat").write_text(_linux_stat_text(12, "Z", 99), encoding="utf-8")
    (proc_root / "13").mkdir()
    (proc_root / "13" / "stat").write_text(_linux_stat_text(13, "S", 7), encoding="utf-8")

    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        "core_tools.provider.process_cleanup._PROC_ROOT",
        str(proc_root),
        raising=False,
    )

    with patch("core_tools.provider.process_cleanup.subprocess.run") as run_ps:
        members = list_process_group_pids(99)
        assert is_pid_alive(11) is True
        assert is_pid_alive(12) is False

    assert members == [10, 11, 12]
    run_ps.assert_not_called()


@pytest.mark.skipif(_pidfd_supported(), reason="covers the non-pidfd fallback path")
def test_non_pidfd_platform_is_fail_closed() -> None:
    assert _pidfd_supported() is False
    identity = ProcessIdentity(pid=os.getpid(), start_time="token")
    with patch("core_tools.provider.process_identity.os.kill") as kill:
        with patch(
            "core_tools.provider.process_identity.inspect_process_identity",
            return_value=IdentityInspectState.LIVE_MATCH,
        ):
            assert _signal_identity(identity, signal.SIGTERM) is False
    kill.assert_not_called()
