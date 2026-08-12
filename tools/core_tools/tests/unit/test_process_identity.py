"""Tests for process-instance identity helpers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.process_cleanup import is_pid_alive
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    _pidfd_supported,
    process_identities_match,
    process_identity_from_termination_record,
    terminate_verified_process_identity,
)


def test_process_identities_match_requires_same_start_time() -> None:
    left = ProcessIdentity(pid=4242, start_time="100")
    right = ProcessIdentity(pid=4242, start_time="100")
    different = ProcessIdentity(pid=4242, start_time="200")

    assert process_identities_match(left, right) is True
    assert process_identities_match(left, different) is False


def test_pidfd_supported_uses_signal_module_not_os() -> None:
    assert _pidfd_supported() == (
        sys.platform == "linux"
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal")
    )


def test_pidfd_supported_does_not_use_os_pidfd_send_signal(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(os, "pidfd_open", lambda pid, flags=0: 1, raising=False)
    monkeypatch.setattr(os, "pidfd_send_signal", lambda fd, sig: None, raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)
    assert _pidfd_supported() is False


def test_process_identity_from_termination_record_preserves_original_identity() -> None:
    record = {
        "pid": 4242,
        "start_time": "100",
        "process_identity": "4242:100",
        "run_id": "run-a",
        "reason": "termination_failed",
    }

    identity = process_identity_from_termination_record(record)

    assert identity == ProcessIdentity(pid=4242, start_time="100", run_id="run-a")


def test_terminate_verified_process_identity_skips_pid_reuse() -> None:
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
                return_value=TerminateIdentityResult.IDENTITY_MISMATCH,
            ) as terminate:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.IDENTITY_MISMATCH
    terminate.assert_called_once_with(identity)


def test_terminate_verified_process_identity_uses_bound_popen() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = None

    with patch(
        "core_tools.provider.process_identity.drain_owned_process_group",
        return_value=True,
    ) as drain:
        result = terminate_verified_process_identity(identity, proc=proc)

    assert result == TerminateIdentityResult.TERMINATED
    drain.assert_called_once()


def test_terminate_verified_process_identity_uses_bound_popen_without_identity() -> None:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = None

    with patch(
        "core_tools.provider.process_identity.drain_owned_process_group",
        return_value=True,
    ) as drain:
        result = terminate_verified_process_identity(None, proc=proc)

    assert result == TerminateIdentityResult.TERMINATED
    drain.assert_called_once()


def test_terminate_verified_process_identity_fails_closed_without_handle() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "core_tools.provider.process_identity._pidfd_supported",
            return_value=False,
        ):
            result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.FAILED


def test_terminate_verified_process_identity_pid_reuse_before_signal_skips_kill() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 9999
    proc.poll.return_value = None

    result = terminate_verified_process_identity(identity, proc=proc)

    assert result == TerminateIdentityResult.IDENTITY_MISMATCH


def test_terminate_linux_identity_uses_pidfd_not_killpg() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=identity,
    ):
        with patch(
            "core_tools.provider.process_identity.capture_process_group_identities",
            return_value=[identity],
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
                        from core_tools.provider.process_identity import _terminate_linux_identity

                        result = _terminate_linux_identity(identity)

    assert result == TerminateIdentityResult.TERMINATED
    killpg.assert_not_called()


@pytest.mark.skipif(sys.platform != "linux", reason="pidfd is Linux-only")
def test_terminate_verified_process_identity_linux_pidfd_path() -> None:
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


@pytest.mark.skipif(
    sys.platform != "linux" or not _pidfd_supported(),
    reason="requires Linux pidfd support",
)
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_terminate_verified_process_identity_kills_child_in_process_group(
    tmp_path: Path,
) -> None:
    from tests.conftest import spawn_sigterm_ignoring_leader_with_child

    proc, child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    start_time = __import__(
        "core_tools.provider.process_identity", fromlist=["read_process_start_time"]
    ).read_process_start_time(proc.pid)
    assert start_time is not None
    identity = ProcessIdentity(pid=proc.pid, start_time=start_time)

    try:
        result = terminate_verified_process_identity(identity)

        assert result == TerminateIdentityResult.TERMINATED
        assert proc.poll() is not None
        assert not is_pid_alive(child_pid)
    finally:
        if is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
