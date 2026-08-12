"""Tests for process-instance identity helpers."""

from __future__ import annotations

from unittest.mock import patch

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
            "core_tools.provider.process_identity.read_process_identity",
            return_value=ProcessIdentity(pid=4242, start_time="999", run_id="run-a"),
        ):
            with patch(
                "core_tools.provider.process_identity.terminate_pid_tree",
            ) as terminate:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.IDENTITY_MISMATCH
    terminate.assert_not_called()


def test_terminate_verified_process_identity_kills_matching_process() -> None:
    identity = ProcessIdentity(pid=4242, start_time="100", run_id="run-a")

    with patch(
        "core_tools.provider.process_identity.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "core_tools.provider.process_identity.read_process_identity",
            return_value=identity,
        ):
            with patch(
                "core_tools.provider.process_identity.terminate_pid_tree",
                return_value=True,
            ) as terminate:
                result = terminate_verified_process_identity(identity)

    assert result == TerminateIdentityResult.TERMINATED
    terminate.assert_called_once_with(4242)
