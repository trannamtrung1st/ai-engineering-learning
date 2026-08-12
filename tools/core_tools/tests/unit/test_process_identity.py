"""Tests for process-instance identity helpers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

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
                "core_tools.provider.process_identity._terminate_linux_pidfd",
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
        "core_tools.provider.process_identity.terminate_process_tree",
        return_value=True,
    ) as terminate:
        result = terminate_verified_process_identity(identity, proc=proc)

    assert result == TerminateIdentityResult.TERMINATED
    terminate.assert_called_once_with(proc)


def test_terminate_verified_process_identity_uses_bound_popen_without_identity() -> None:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 4242
    proc.poll.return_value = None

    with patch(
        "core_tools.provider.process_identity.terminate_process_tree",
        return_value=True,
    ) as terminate:
        result = terminate_verified_process_identity(None, proc=proc)

    assert result == TerminateIdentityResult.TERMINATED
    terminate.assert_called_once_with(proc)


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


def test_terminate_linux_pidfd_terminates_process_group_not_only_leader() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        return_value=identity,
    ):
        with patch(
            "core_tools.provider.process_identity.read_process_group_id",
            return_value=4242,
        ):
            with patch("core_tools.provider.process_identity.os.killpg") as killpg:
                with patch(
                    "core_tools.provider.process_identity._wait_process_group_gone",
                    return_value=True,
                ):
                    from core_tools.provider.process_identity import _terminate_linux_pidfd

                    result = _terminate_linux_pidfd(identity)

    assert result == TerminateIdentityResult.TERMINATED
    killpg.assert_called()


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
                "core_tools.provider.process_identity._terminate_linux_pidfd",
                return_value=TerminateIdentityResult.TERMINATED,
            ) as terminate:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.TERMINATED
    terminate.assert_called_once_with(identity)


@pytest.mark.skipif(
    sys.platform != "linux" or not _pidfd_supported(),
    reason="requires Linux pidfd support",
)
def test_terminate_verified_process_identity_kills_child_in_process_group() -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import os, signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "os.setpgrp(); "
                "child = os.fork() or (time.sleep(60), os._exit(0))[1]; "
                "time.sleep(60)"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.1)
    start_time = __import__(
        "core_tools.provider.process_identity", fromlist=["read_process_start_time"]
    ).read_process_start_time(proc.pid)
    assert start_time is not None
    identity = ProcessIdentity(pid=proc.pid, start_time=start_time)

    result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.TERMINATED
    assert proc.poll() is not None
