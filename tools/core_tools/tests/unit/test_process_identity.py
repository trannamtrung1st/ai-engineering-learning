"""Tests for process-instance identity helpers."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    process_identities_match,
    terminate_verified_process_identity,
)


def test_process_identities_match_requires_same_start_time() -> None:
    left = ProcessIdentity(pid=4242, start_time="100")
    right = ProcessIdentity(pid=4242, start_time="100")
    different = ProcessIdentity(pid=4242, start_time="200")

    assert process_identities_match(left, right) is True
    assert process_identities_match(left, different) is False


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
            with patch(
                "core_tools.provider.process_identity.terminate_pid_tree",
            ) as terminate:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.FAILED
    terminate.assert_not_called()


def test_terminate_verified_process_identity_pid_reuse_before_signal_skips_kill() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = 9999
    proc.poll.return_value = None

    result = terminate_verified_process_identity(identity, proc=proc)

    assert result == TerminateIdentityResult.IDENTITY_MISMATCH


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
