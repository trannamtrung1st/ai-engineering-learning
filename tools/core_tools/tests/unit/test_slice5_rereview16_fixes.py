"""Slice 5 sixteenth re-review regressions (S5-RR16-001 through S5-RR16-003)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_cleanup import (
    LinuxProcStat,
    PidInspectResult,
    PidInspectState,
    ProcessGroupState,
    is_pid_alive,
    list_process_group_pids,
    process_group_state,
    terminate_process_tree,
)
from core_tools.provider.process_identity import IdentityInspectState, ProcessIdentity
from core_tools.provider.session_janitor import janitor_command
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


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_janitor_cleans_descendants_after_agent_exits(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        f"agent_pid_file = {str(tmp_path / 'agent.pid')!r}\n"
        "with open(agent_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    child_pid = None
    try:
        for _ in range(40):
            if child_pid_file.exists():
                child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                break
            import time

            time.sleep(0.05)
        assert child_pid is not None
        os.kill(child_pid, 0)
        cleaned = terminate_process_tree(proc)
        assert cleaned is True
        assert proc.poll() is not None
        assert is_pid_alive(child_pid) is False
    finally:
        if child_pid is not None and is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_janitor_cleans_descendants_after_unexpected_agent_exit(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    agent_pid_file = tmp_path / "agent.pid"
    script = (
        "import os, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        f"agent_pid_file = {str(agent_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "with open(agent_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    child_pid = None
    try:
        import time

        for _ in range(40):
            if child_pid_file.exists() and agent_pid_file.exists():
                child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                break
            time.sleep(0.05)
        assert child_pid is not None
        agent_pid = int(agent_pid_file.read_text(encoding="utf-8").strip())
        os.kill(agent_pid, signal.SIGKILL)
        cleaned = terminate_process_tree(proc)
        assert cleaned is True
        assert is_pid_alive(child_pid) is False
        assert proc.poll() is not None
    finally:
        if child_pid is not None and is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_bound_tree_cleanup_is_idempotent_after_success(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert terminate_process_tree(proc) is True
        assert terminate_process_tree(proc) is True
        assert proc.poll() is not None
        assert process_group_state(proc.pid) is ProcessGroupState.GONE
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_tracked_tree_is_not_live_when_owned_identities_gone_and_group_gone(
    tmp_path: Path,
) -> None:
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

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.GONE,
        ):
            assert provider._tracked_tree_is_live(
                provider._tracked_turn_procs[4242]
            ) is False
            provider.reconcile_terminated_pids([5151])

    assert 4242 not in provider._tracked_turn_procs
    assert provider.list_active_sessions() == []


def test_tracked_tree_stays_unresolved_when_group_is_unverifiable(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader,),
    )

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.UNVERIFIABLE,
        ):
            assert provider._tracked_tree_is_live(
                provider._tracked_turn_procs[4242]
            ) is True


def test_live_group_without_observed_gone_stays_unresolved(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader,),
    )

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.LIVE,
        ):
            with patch(
                "core_tools.provider.cursor.inspect_process_identity",
                return_value=IdentityInspectState.IDENTITY_MISMATCH,
            ):
                assert provider._tracked_tree_is_live(
                    provider._tracked_turn_procs[4242]
                ) is False


def test_unrelated_unreadable_proc_does_not_poison_target_group(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        "core_tools.provider.process_cleanup._linux_proc_available",
        lambda: True,
    )

    def fake_read(pid: int) -> PidInspectResult:
        if pid == 100:
            return PidInspectResult(
                PidInspectState.LIVE,
                LinuxProcStat(pid=100, state="S", pgid=99, start_time="1"),
            )
        if pid == 200:
            return PidInspectResult(PidInspectState.UNVERIFIABLE)
        return PidInspectResult(PidInspectState.GONE)

    with patch(
        "core_tools.provider.process_cleanup.os.listdir",
        return_value=["100", "200"],
    ):
        with patch(
            "core_tools.provider.process_cleanup._read_linux_proc_stat",
            side_effect=fake_read,
        ):
            with patch(
                "core_tools.provider.process_cleanup.os.getpgid",
                side_effect=lambda pid: 1 if pid == 200 else 99,
            ):
                assert list_process_group_pids(99) == [100]
                assert process_group_state(99) is ProcessGroupState.LIVE


def test_unreadable_proc_in_target_group_is_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        "core_tools.provider.process_cleanup._linux_proc_available",
        lambda: True,
    )

    def fake_read(pid: int) -> PidInspectResult:
        if pid == 100:
            return PidInspectResult(
                PidInspectState.LIVE,
                LinuxProcStat(pid=100, state="S", pgid=99, start_time="1"),
            )
        return PidInspectResult(PidInspectState.UNVERIFIABLE)

    with patch(
        "core_tools.provider.process_cleanup.os.listdir",
        return_value=["100", "200"],
    ):
        with patch(
            "core_tools.provider.process_cleanup._read_linux_proc_stat",
            side_effect=fake_read,
        ):
            with patch(
                "core_tools.provider.process_cleanup.os.getpgid",
                side_effect=lambda pid: 99,
            ):
                assert list_process_group_pids(99) is None
                assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE


def test_unreadable_proc_without_pgid_query_is_unverifiable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        "core_tools.provider.process_cleanup._linux_proc_available",
        lambda: True,
    )

    def fake_read(pid: int) -> PidInspectResult:
        if pid == 100:
            return PidInspectResult(
                PidInspectState.LIVE,
                LinuxProcStat(pid=100, state="S", pgid=99, start_time="1"),
            )
        return PidInspectResult(PidInspectState.UNVERIFIABLE)

    with patch(
        "core_tools.provider.process_cleanup.os.listdir",
        return_value=["100", "200"],
    ):
        with patch(
            "core_tools.provider.process_cleanup._read_linux_proc_stat",
            side_effect=fake_read,
        ):
            with patch(
                "core_tools.provider.process_cleanup.os.getpgid",
                side_effect=OSError,
            ):
                assert list_process_group_pids(99) is None
                assert process_group_state(99) is ProcessGroupState.UNVERIFIABLE
