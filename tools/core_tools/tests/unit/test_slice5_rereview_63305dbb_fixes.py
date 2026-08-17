"""Slice 5 rereview 63305dbb: session-scoped late adopt, reap ownership, no raw PID kill."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    is_pid_alive,
    process_group_state,
)
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    drain_owned_process_group,
    terminate_verified_process_identity,
)


def test_process_group_state_treats_zombie_only_members_as_gone() -> None:
    with patch(
        "core_tools.provider.process_cleanup.list_process_group_pids",
        return_value=[4242],
    ), patch(
        "core_tools.provider.process_cleanup.inspect_pid_liveness",
        return_value=PidInspectState.ZOMBIE,
    ):
        assert process_group_state(99) is ProcessGroupState.GONE


def test_drain_does_not_reap_unknown_identities_when_targets_empty() -> None:
    leader = ProcessIdentity(pid=4242, start_time="leader")
    foreign = ProcessIdentity(pid=5151, start_time="foreign")
    reaped: list[int] = []

    def fake_reap(identity: ProcessIdentity) -> None:
        reaped.append(identity.pid)

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        side_effect=[
            ProcessGroupState.LIVE,
            ProcessGroupState.LIVE,
            ProcessGroupState.GONE,
        ],
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=[foreign],
    ), patch(
        "core_tools.provider.process_identity._identity_still_alive",
        return_value=True,
    ), patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ), patch(
        "core_tools.provider.process_identity._group_still_ours",
        return_value=True,
    ), patch(
        "core_tools.provider.process_identity.is_owned_session_leader",
        return_value=False,
    ), patch(
        "core_tools.provider.process_identity._reap_identity",
        side_effect=fake_reap,
    ), patch(
        "core_tools.provider.process_identity._signal_identity",
        return_value=True,
    ):
        drain_owned_process_group(
            pgid=99,
            leader_identity=leader,
            known_identities=[leader],
            timeout=0.2,
        )

    assert 5151 not in reaped


def test_non_pidfd_signal_never_raw_kills_reusable_pid() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100")
    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=False,
    ), patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        return_value=IdentityInspectState.LIVE_MATCH,
    ), patch(
        "core_tools.provider.process_identity.read_process_start_time",
        return_value="100",
    ), patch(
        "core_tools.provider.process_identity.os.kill",
    ) as kill:
        from core_tools.provider.process_identity import _signal_identity

        assert _signal_identity(identity, signal.SIGKILL) is False
    kill.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_owned_session_late_fork_is_drained(tmp_path: Path) -> None:
    child_file = tmp_path / "late.pid"
    script = (
        "import os, time, sys\n"
        f"path = {str(child_file)!r}\n"
        "sys.stdout.write('ready\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(0.15)\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(path, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert "ready" in line
        from core_tools.provider.process_identity import read_process_identity

        leader = read_process_identity(proc.pid)
        assert leader is not None
        deadline = time.monotonic() + 2.0
        child_pid = None
        while time.monotonic() < deadline:
            if child_file.exists():
                child_pid = int(child_file.read_text(encoding="utf-8").strip())
                break
            time.sleep(0.05)
        assert child_pid is not None
        assert is_pid_alive(child_pid)
        cleaned = drain_owned_process_group(
            pgid=proc.pid,
            leader_identity=leader,
            known_identities=[leader],
            timeout=2.0,
        )
        assert cleaned is True
        assert proc.poll() is not None
        assert not is_pid_alive(child_pid)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX waitpid ownership")
def test_foreign_exiting_sibling_wait_status_survives_owned_session_drain() -> None:
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.05); raise SystemExit(17)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        from core_tools.provider.process_identity import read_process_identity

        leader = read_process_identity(target.pid)
        assert leader is not None
        drain_owned_process_group(
            pgid=target.pid,
            leader_identity=leader,
            known_identities=[leader],
            timeout=1.0,
        )
        assert sibling.wait(timeout=2.0) == 17
    finally:
        if target.poll() is None:
            target.kill()
            target.wait(timeout=2.0)
        if sibling.poll() is None:
            sibling.kill()
            sibling.wait(timeout=2.0)


def test_pid_reuse_after_identity_check_never_signals_replacement() -> None:
    identity = ProcessIdentity(pid=4242, start_time="original")
    inspect_states = iter(
        [
            IdentityInspectState.LIVE_MATCH,
            IdentityInspectState.IDENTITY_MISMATCH,
        ]
    )

    def fake_inspect(_identity: ProcessIdentity, *, timeout: float | None = None):
        try:
            return next(inspect_states)
        except StopIteration:
            return IdentityInspectState.IDENTITY_MISMATCH

    destructive: list[tuple[int, int]] = []
    real_kill = os.kill

    def tracking_kill(pid: int, sig: int) -> None:
        if sig != 0:
            destructive.append((pid, sig))
        if sig == 0:
            raise ProcessLookupError()
        real_kill(pid, sig)

    with patch(
        "core_tools.provider.process_identity._pidfd_supported",
        return_value=False,
    ), patch(
        "core_tools.provider.process_identity.inspect_process_identity",
        side_effect=fake_inspect,
    ), patch(
        "core_tools.provider.process_identity.is_owned_session_leader",
        return_value=False,
    ), patch(
        "core_tools.provider.process_identity.os.kill",
        side_effect=tracking_kill,
    ) as kill, patch(
        "core_tools.provider.process_identity.os.killpg",
    ) as killpg:
        from core_tools.provider.process_identity import TerminateIdentityResult

        result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.FAILED
    assert destructive == []
    assert all(call.args[1] == 0 for call in kill.call_args_list)
    killpg.assert_not_called()
