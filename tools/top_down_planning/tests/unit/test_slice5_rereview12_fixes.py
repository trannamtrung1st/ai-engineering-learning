"""Slice 5 twelfth re-review regression tests (S5-RR12-001 through S5-RR12-003)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import (
    is_pid_alive,
    terminate_pid_tree,
    terminate_process_tree,
)
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    drain_owned_process_group,
    terminate_verified_process_identity,
)


def _spawn_sigterm_ignoring_leader_with_child(
    tmp_path: Path,
) -> tuple[subprocess.Popen[str], int]:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    for _ in range(40):
        if child_pid_file.exists():
            return proc, int(child_pid_file.read_text(encoding="utf-8").strip())
        time.sleep(0.05)
    proc.kill()
    proc.wait(timeout=5)
    raise AssertionError("child PID file was not written")


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_terminate_process_tree_cleans_group_when_leader_already_exited(
    tmp_path: Path,
) -> None:
    from core_tools.provider.process_identity import read_process_identity

    proc, child_pid = _spawn_sigterm_ignoring_leader_with_child(tmp_path)
    leader_identity = read_process_identity(proc.pid)
    child_identity = read_process_identity(child_pid)
    assert leader_identity is not None
    assert child_identity is not None
    pgid = os.getpgid(proc.pid)
    members = [leader_identity, child_identity]

    proc.kill()
    proc.wait(timeout=5)

    try:
        cleaned = terminate_process_tree(
            proc,
            pgid=pgid,
            leader_identity=leader_identity,
            member_identities=members,
        )
        from core_tools.provider.process_identity import _pidfd_supported

        child_alive = is_pid_alive(child_pid)
        if _pidfd_supported():
            assert cleaned is True
            assert not child_alive
        else:
            assert not (cleaned is True and child_alive)
    finally:
        if is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_drain_owned_process_group_discovers_late_fork(tmp_path: Path) -> None:
    go_file = tmp_path / "go"
    late_child_file = tmp_path / "late_child.pid"
    script = (
        "import os, time\n"
        f"go_file = {str(go_file)!r}\n"
        f"late_child_file = {str(late_child_file)!r}\n"
        "while not os.path.exists(go_file):\n"
        "    time.sleep(0.01)\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(late_child_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.05)
    leader = ProcessIdentity(pid=proc.pid, start_time="leader")
    pgid = os.getpgid(proc.pid)
    first = {"seen": False}

    import core_tools.provider.process_identity as identity_mod

    original = identity_mod._current_group_identities

    def wrapped(pgid_value: int, *, run_id: str | None = None, timeout: float | None = None):
        members = original(pgid_value, run_id=run_id, timeout=timeout)
        if not first["seen"]:
            first["seen"] = True
            go_file.write_text("go", encoding="utf-8")
            for _ in range(40):
                if late_child_file.exists():
                    break
                time.sleep(0.05)
        return members

    late_child_pid: int | None = None
    try:
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            side_effect=wrapped,
        ):
            with patch(
                "core_tools.provider.process_identity.read_process_identity",
                side_effect=lambda pid, **_: ProcessIdentity(
                    pid=pid,
                    start_time="leader" if pid == proc.pid else f"member-{pid}",
                ),
            ):
                result = drain_owned_process_group(
                    pgid=pgid,
                    leader_identity=leader,
                    known_identities=[leader],
                )
        late_child_pid = (
            int(late_child_file.read_text(encoding="utf-8").strip())
            if late_child_file.exists()
            else None
        )
        child_alive = late_child_pid is not None and is_pid_alive(late_child_pid)
        assert not (result is True and child_alive)
    finally:
        if late_child_pid is not None and is_pid_alive(late_child_pid):
            os.kill(late_child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_drain_owned_process_group_does_not_signal_reused_pgid() -> None:
    original_leader = ProcessIdentity(pid=4242, start_time="100")
    reused_member = ProcessIdentity(pid=5151, start_time="200")

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=__import__(
            "core_tools.provider.process_cleanup",
            fromlist=["ProcessGroupState"],
        ).ProcessGroupState.LIVE,
    ):
        with patch(
            "core_tools.provider.process_identity._current_group_identities",
            return_value=[reused_member],
        ):
            with patch(
                "core_tools.provider.process_identity._group_still_ours",
                return_value=False,
            ):
                with patch(
                    "core_tools.provider.process_identity._signal_identity",
                ) as signal_identity:
                    result = drain_owned_process_group(
                        pgid=4242,
                        leader_identity=original_leader,
                        known_identities=[original_leader],
                    )

    assert result is False
    signal_identity.assert_not_called()


def test_terminate_pid_tree_uses_identity_safe_drain() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100")

    with patch(
        "core_tools.provider.process_identity.drain_owned_process_group",
        return_value=True,
    ) as drain:
        assert terminate_pid_tree(4242, leader_identity=identity) is True

    drain.assert_called_once()


def test_cursor_runner_finalizer_keeps_tracking_when_tree_cleanup_fails(
    tmp_path: Path,
) -> None:
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
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._set_collect_context(session_id, "planner")
    provider._register_tracked_turn_proc(proc)

    with patch(
        "core_tools.provider.cursor.terminate_process_tree",
        return_value=False,
    ) as terminate_tree:
        tracked = provider._tracked_turn_procs.get(proc.pid)
        tree_clean = terminate_tree(
            proc,
            pgid=tracked.pgid if tracked is not None else None,
            leader_identity=tracked.identity if tracked is not None else None,
            member_identities=(
                list(tracked.member_identities)
                if tracked is not None and tracked.member_identities is not None
                else None
            ),
        )
        if tree_clean:
            provider._unregister_tracked_turn_proc(proc)

    assert proc.pid in provider._tracked_turn_procs
    proc.kill()
    proc.wait(timeout=5)
