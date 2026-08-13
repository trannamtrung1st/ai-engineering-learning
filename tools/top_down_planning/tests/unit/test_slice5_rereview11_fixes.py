"""Slice 5 eleventh re-review regression tests (S5-RR11-001 through S5-RR11-003)."""

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
    ProcessGroupState,
    is_pid_alive,
    process_group_state,
    terminate_process_tree,
)
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    _terminate_linux_identity,
    terminate_verified_process_identity,
)


def _spawn_leader_with_sigterm_ignoring_child(
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
def test_terminate_process_tree_kills_sigterm_ignoring_child(tmp_path: Path) -> None:
    proc, child_pid = _spawn_leader_with_sigterm_ignoring_child(tmp_path)
    try:
        from core_tools.provider.process_identity import _pidfd_supported

        cleaned = terminate_process_tree(proc)
        child_alive = is_pid_alive(child_pid)
        if _pidfd_supported():
            assert cleaned is True
            assert proc.poll() is not None
            assert not child_alive
        else:
            assert not (cleaned is True and child_alive)
    finally:
        if is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_process_group_state_unverifiable_without_proc(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(os.path, "isdir", lambda path: False)
    assert process_group_state(4242) is ProcessGroupState.UNVERIFIABLE


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_terminate_process_tree_fails_closed_when_group_unverifiable(
    monkeypatch,
) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        monkeypatch.setattr(sys, "platform", "linux", raising=False)
        monkeypatch.setattr(os.path, "isdir", lambda path: False)
        assert terminate_process_tree(proc) is False
        # Bound Popen may still terminate the leader; PGID occupants must not be signaled.
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_terminate_linux_identity_uses_pidfd_not_killpg() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    captured = [identity]

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=identity,
    ):
        with patch(
            "core_tools.provider.process_identity.capture_process_group_identities",
            return_value=captured,
        ):
            with patch(
                "core_tools.provider.process_identity._signal_identity",
                return_value=True,
            ) as signal_identity:
                with patch(
                    "core_tools.provider.process_identity.drain_owned_process_group",
                    return_value=True,
                ):
                    with patch("core_tools.provider.process_identity.os.killpg") as killpg:
                        result = _terminate_linux_identity(identity)

    assert result == TerminateIdentityResult.TERMINATED
    killpg.assert_not_called()


def test_terminate_linux_identity_does_not_kill_reused_group_members() -> None:
    original = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    reused = ProcessIdentity(pid=4242, start_time="200", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=reused,
    ):
        with patch(
            "core_tools.provider.process_identity._signal_identity_via_pidfd",
        ) as signal_identity:
            result = _terminate_linux_identity(original)

    assert result == TerminateIdentityResult.IDENTITY_MISMATCH
    signal_identity.assert_not_called()


def test_terminate_linux_identity_skips_pidfd_when_leader_exits_before_signal() -> None:
    original = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=original,
    ):
        with patch(
            "core_tools.provider.process_identity.capture_process_group_identities",
            return_value=[original],
        ):
            with patch(
                "core_tools.provider.process_identity._identity_still_alive",
                return_value=False,
            ):
                with patch(
                    "core_tools.provider.process_identity._wait_identities_dead",
                    return_value=True,
                ):
                    with patch(
                        "core_tools.provider.process_identity.os.pidfd_open",
                        create=True,
                    ) as pidfd_open:
                        result = _terminate_linux_identity(original)

    assert result == TerminateIdentityResult.TERMINATED
    pidfd_open.assert_not_called()


def test_terminate_linux_identity_does_not_escalate_kill_to_reused_identities() -> None:
    original = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=original,
    ):
        with patch(
            "core_tools.provider.process_identity.capture_process_group_identities",
            return_value=[original],
        ):
            with patch(
                "core_tools.provider.process_identity.drain_owned_process_group",
                return_value=False,
            ):
                result = _terminate_linux_identity(original)

    assert result == TerminateIdentityResult.FAILED


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="pidfd identity termination is Linux-only",
)
def test_terminate_verified_process_identity_pidfd_signals_leader() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "core_tools.provider.process_identity._pidfd_supported",
            return_value=True,
        ):
            with patch(
                "core_tools.provider.process_identity._terminate_linux_identity",
                return_value=TerminateIdentityResult.TERMINATED,
            ) as terminate:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.TERMINATED
    terminate.assert_called_once_with(identity)
