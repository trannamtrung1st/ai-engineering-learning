"""Slice 5 rereview 69b37818: fail-closed session adopt, reap vs gone, one deadline."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    process_group_state,
)
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
    _lineage_allows_session_adopt,
    drain_owned_process_group,
    terminate_verified_process_identity,
)


def test_matching_run_ids_allow_session_adopt() -> None:
    leader = ProcessIdentity(pid=1, start_time="l", run_id="A")
    member = ProcessIdentity(pid=2, start_time="m", run_id="A")
    assert _lineage_allows_session_adopt(leader, member) is True


def test_leader_run_without_member_run_rejects_session_adopt() -> None:
    leader = ProcessIdentity(pid=1, start_time="l", run_id="A")
    member = ProcessIdentity(pid=2, start_time="m", run_id=None)
    assert _lineage_allows_session_adopt(leader, member) is False


def test_member_run_without_leader_run_rejects_session_adopt() -> None:
    leader = ProcessIdentity(pid=1, start_time="l", run_id=None)
    member = ProcessIdentity(pid=2, start_time="m", run_id="A")
    assert _lineage_allows_session_adopt(leader, member) is False


def test_missing_lineage_on_both_rejects_session_adopt() -> None:
    leader = ProcessIdentity(pid=1, start_time="l")
    member = ProcessIdentity(pid=2, start_time="m")
    assert _lineage_allows_session_adopt(leader, member) is False


def test_tdp_agent_in_foreign_session_does_not_killpg() -> None:
    agent = ProcessIdentity(
        pid=5151, start_time="agent", run_id="run-a", owner_id="owner-a"
    )
    leader = ProcessIdentity(pid=4242, start_time="leader")

    def fake_owned(identity, *, pgid=None, timeout=None):
        del pgid, timeout
        return identity.pid == leader.pid

    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=False,
    ), patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ), patch(
        "core_tools.provider.process_identity.is_owned_session_leader",
        side_effect=fake_owned,
    ), patch(
        "core_tools.provider.process_identity.read_process_group_id",
        return_value=leader.pid,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=leader,
    ), patch(
        "core_tools.provider.process_identity.os.killpg",
    ) as killpg:
        result = terminate_verified_process_identity(agent)

    assert result is TerminateIdentityResult.FAILED
    killpg.assert_not_called()


def test_linux_identity_does_not_promote_no_lineage_session() -> None:
    agent = ProcessIdentity(pid=5151, start_time="agent", run_id="run-a")
    leader = ProcessIdentity(pid=4242, start_time="leader")

    def fake_owned(identity, *, pgid=None, timeout=None):
        del pgid, timeout
        return identity.pid == leader.pid

    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=True,
    ), patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ), patch(
        "core_tools.provider.process_identity.is_owned_session_leader",
        side_effect=fake_owned,
    ), patch(
        "core_tools.provider.process_identity.read_process_group_id",
        return_value=leader.pid,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=leader,
    ), patch(
        "core_tools.provider.process_identity.capture_process_group_identities",
        return_value=[agent],
    ), patch(
        "core_tools.provider.process_identity.drain_owned_process_group",
        return_value=True,
    ) as drain, patch(
        "core_tools.provider.process_identity.os.killpg",
    ) as killpg:
        terminate_verified_process_identity(agent)

    killpg.assert_not_called()
    drain.assert_called()
    kwargs = drain.call_args.kwargs
    assert kwargs["leader_identity"] == agent
    assert kwargs["leader_identity"] != leader


def test_zombie_only_group_is_not_gone(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    with patch(
        "core_tools.provider.process_cleanup.list_process_group_pids",
        return_value=[4242],
    ), patch(
        "core_tools.provider.process_cleanup.inspect_pid_liveness",
        return_value=PidInspectState.ZOMBIE,
    ):
        state = process_group_state(99)
    assert state is not ProcessGroupState.GONE
    assert state is not ProcessGroupState.LIVE
    assert state is ProcessGroupState.ZOMBIE_ONLY


def test_drain_does_not_succeed_until_waitpid_reaps_zombie_child() -> None:
    child = ProcessIdentity(pid=4242, start_time="child")
    waitpid_hits: list[int] = []
    consumed = {"done": False}

    def tracking_waitpid(pid: int, flags: int):
        del flags
        waitpid_hits.append(pid)
        if consumed["done"] and pid == child.pid:
            return (pid, 0)
        return (0, 0)

    def fake_present(identity: ProcessIdentity, *, timeout: float | None = None) -> bool:
        del timeout
        return identity.pid == child.pid and not consumed["done"]

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.GONE,
    ), patch(
        "core_tools.provider.process_identity._identity_still_present",
        side_effect=fake_present,
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=[],
    ), patch(
        "core_tools.provider.process_cleanup.os.waitpid",
        side_effect=tracking_waitpid,
    ), patch(
        "core_tools.provider.process_identity.os.waitpid",
        side_effect=tracking_waitpid,
    ):
        first = drain_owned_process_group(
            pgid=99,
            leader_identity=child,
            known_identities=[child],
            timeout=0.2,
        )
        assert first is False
        assert child.pid in waitpid_hits
        consumed["done"] = True
        cleaned = drain_owned_process_group(
            pgid=99,
            leader_identity=child,
            known_identities=[child],
            timeout=0.2,
        )

    assert cleaned is True


def test_process_group_state_nested_inspects_share_one_deadline(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    members = list(range(10, 20))
    clock = {"t": 0.0}
    inspect_timeouts: list[float | None] = []

    def fake_monotonic() -> float:
        return clock["t"]

    def fake_list(pgid: int, *, timeout: float | None = None):
        del pgid
        return members

    def fake_inspect(pid: int, *, timeout: float | None = None):
        del pid
        inspect_timeouts.append(timeout)
        clock["t"] += 0.03
        return PidInspectState.LIVE

    with patch(
        "core_tools.provider.process_cleanup.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.process_cleanup.list_process_group_pids",
        side_effect=fake_list,
    ), patch(
        "core_tools.provider.process_cleanup.inspect_pid_liveness",
        side_effect=fake_inspect,
    ):
        process_group_state(99, timeout=0.1)

    assert clock["t"] < 0.2
    assert inspect_timeouts
    assert inspect_timeouts[0] is not None
    assert inspect_timeouts[0] <= 0.1
    assert inspect_timeouts[-1] is not None
    assert inspect_timeouts[-1] < inspect_timeouts[0]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_abort_timeout_keeps_tracking_then_reaps_session(tmp_path: Path) -> None:
    from core_tools.provider.cursor import CursorProvider
    from core_tools.provider.errors import ProviderLifecycleTimeoutError
    from tests.conftest import (
        reap_process_group,
        spawn_sigterm_ignoring_leader_with_child,
        tracked_turn_proc,
    )

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
    proc, child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc(
        session_id,
        "planner",
        proc.pid,
        proc=proc,
    )
    try:
        with pytest.raises(ProviderLifecycleTimeoutError):
            provider.abort_turn(session_id, timeout=0.3)
        assert proc.pid in provider._tracked_turn_procs
    finally:
        reap_process_group(proc, extra_pids=(child_pid,))
