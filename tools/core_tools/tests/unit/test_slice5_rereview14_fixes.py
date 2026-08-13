"""Slice 5 fourteenth re-review regressions (S5-RR14-001 through S5-RR14-002)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    is_pid_alive,
    list_process_group_pids,
    process_group_state,
)
from core_tools.provider.process_identity import (
    ProcessIdentity,
    drain_owned_process_group,
)


def _linux_stat_text(pid: int, state: str, pgid: int, start_time: str = "999") -> str:
    fields = [state, "1", str(pgid)] + ["0"] * 16 + [start_time]
    return f"{pid} (cmd) {' '.join(fields)}\n"


def _linux_proc(tmp_path: Path, monkeypatch) -> Path:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        "core_tools.provider.process_cleanup._PROC_ROOT",
        str(proc_root),
        raising=False,
    )
    return proc_root


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


def test_proc_stat_permission_error_is_not_treated_as_dead(
    tmp_path: Path, monkeypatch
) -> None:
    proc_root = _linux_proc(tmp_path, monkeypatch)
    (proc_root / "11").mkdir()
    (proc_root / "11" / "stat").write_text(_linux_stat_text(11, "S", 99), encoding="utf-8")

    import core_tools.provider.process_cleanup as cleanup

    def deny_stat(path, *args, **kwargs):
        if str(path).endswith("/11/stat"):
            raise PermissionError("denied")
        return open(path, *args, **kwargs)

    monkeypatch.setattr(cleanup, "open", deny_stat, raising=False)

    assert is_pid_alive(11) is True
    assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE
    assert list_process_group_pids(99) is None


def test_malformed_proc_stat_fails_closed(tmp_path: Path, monkeypatch) -> None:
    proc_root = _linux_proc(tmp_path, monkeypatch)
    (proc_root / "11").mkdir()
    (proc_root / "11" / "stat").write_text("not-a-stat\n", encoding="utf-8")

    assert is_pid_alive(11) is True
    assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE


def test_unreadable_group_member_makes_group_unverifiable(
    tmp_path: Path, monkeypatch
) -> None:
    proc_root = _linux_proc(tmp_path, monkeypatch)
    (proc_root / "10").mkdir()
    (proc_root / "10" / "stat").write_text(_linux_stat_text(10, "S", 99), encoding="utf-8")
    (proc_root / "11").mkdir()
    (proc_root / "11" / "stat").write_text(_linux_stat_text(11, "S", 99), encoding="utf-8")

    import core_tools.provider.process_cleanup as cleanup

    def deny_member(path, *args, **kwargs):
        if str(path).endswith("/11/stat"):
            raise PermissionError("denied")
        return open(path, *args, **kwargs)

    monkeypatch.setattr(cleanup, "open", deny_member, raising=False)

    assert list_process_group_pids(99) is None
    assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE


def test_drain_fails_closed_when_group_is_unverifiable() -> None:
    leader = ProcessIdentity(pid=4242, start_time="100")
    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.UNVERIFIABLE,
    ):
        with patch(
            "core_tools.provider.process_identity._signal_identity",
        ) as signal_identity:
            result = drain_owned_process_group(
                pgid=4242,
                leader_identity=leader,
                known_identities=[leader],
            )
    assert result is False
    signal_identity.assert_not_called()


def test_darwin_ps_nonzero_is_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    result = MagicMock(returncode=1, stdout="", stderr="ps: failed to inspect process group")
    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        return_value=result,
    ):
        assert list_process_group_pids(99) is None
        assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE


def test_darwin_ps_empty_group_with_nonzero_is_gone(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    result = MagicMock(returncode=1, stdout="", stderr="")
    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        return_value=result,
    ):
        assert list_process_group_pids(99) == []
        assert process_group_state(99) is ProcessGroupState.GONE


def test_darwin_malformed_pid_output_is_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    result = MagicMock(returncode=0, stdout="not-a-pid\n")
    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        return_value=result,
    ):
        assert list_process_group_pids(99) is None
        assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE


def test_surviving_pids_exclude_reused_member_pid(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    records = [
        {
            "pid": 4242,
            "reason": "termination_failed",
            "tree_status": "unresolved",
            "member_pids": [4242, 5151],
            "member_identities": ["4242:100", "5151:200"],
            "start_time": "100",
            "process_identity": "4242:100",
        }
    ]

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=True):
        with patch(
            "core_tools.provider.cursor.process_identity_is_live",
            return_value=False,
        ):
            surviving = provider._surviving_pids_for_session(session_id, records)

    assert surviving == ()
    assert 5151 not in surviving


def test_legacy_pid_only_failure_record_does_not_trust_current_occupant(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    records = [{"pid": 4242, "reason": "termination_failed"}]

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=True):
        surviving = provider._surviving_pids_for_session(session_id, records)

    assert surviving == ()


def test_terminate_session_does_not_fail_on_reused_member_pid(tmp_path: Path) -> None:
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

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=True):
        with patch(
            "core_tools.provider.cursor.process_identity_is_live",
            return_value=False,
        ):
            with patch(
                "core_tools.provider.cursor.terminate_verified_process_identity",
                return_value=__import__(
                    "core_tools.provider.process_identity",
                    fromlist=["TerminateIdentityResult"],
                ).TerminateIdentityResult.ALREADY_GONE,
            ):
                provider.terminate_session(session_id)

    assert session_id not in provider._sessions
