"""Slice 5 rereview 6495b53: only a session leader may authorize group SIGKILL."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.process_identity import _fallback_kill_bound_janitor_group
from core_tools.provider.session_janitor import (
    DrainResult,
    _leader_still_owns_group,
    _process_start_token,
    _run_escalation,
)


def test_non_leader_member_does_not_own_group_even_with_matching_start_token() -> None:
    start = "100.000001"
    with patch(
        "core_tools.provider.session_janitor.os.getpgid",
        return_value=4242,
    ), patch(
        "core_tools.provider.session_janitor.os.getsid",
        return_value=4242,
    ), patch(
        "core_tools.provider.session_janitor._process_start_token",
        return_value=start,
    ):
        assert _leader_still_owns_group(4242, 9999, start) is False


def test_session_leader_with_matching_start_token_owns_group() -> None:
    start = "100.000001"
    with patch(
        "core_tools.provider.session_janitor.os.getpgid",
        return_value=4242,
    ), patch(
        "core_tools.provider.session_janitor.os.getsid",
        return_value=4242,
    ), patch(
        "core_tools.provider.session_janitor._process_start_token",
        return_value=start,
    ):
        assert _leader_still_owns_group(4242, 4242, start) is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_pytest_process_cannot_authorize_runner_group_killpg() -> None:
    leader_pid = os.getpid()
    pgid = os.getpgrp()
    if leader_pid == pgid:
        pytest.skip("pytest is the process-group leader in this environment")
    start = _process_start_token(leader_pid)
    assert start
    assert _leader_still_owns_group(pgid, leader_pid, start) is False

    go_r, go_w = os.pipe()
    result_r, result_w = os.pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    try:
        with patch("core_tools.provider.session_janitor.os.killpg") as killpg:
            _run_escalation(
                pgid=pgid,
                status_fd=None,
                handshake_fd=None,
                go_fd=go_r,
                result_fd=result_w,
                agent_code=0,
                stop_requested=False,
                leader_pid=leader_pid,
                leader_start=start,
            )
        killpg.assert_not_called()
    finally:
        for fd in (go_r, result_r, result_w):
            try:
                os.close(fd)
            except OSError:
                pass


def test_escalation_does_not_killpg_when_leader_pid_differs_from_pgid() -> None:
    start = "100.000001"
    go_r, go_w = os.pipe()
    result_r, result_w = os.pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    try:
        with patch(
            "core_tools.provider.session_janitor.os.getpgid",
            return_value=4242,
        ), patch(
            "core_tools.provider.session_janitor.os.getsid",
            return_value=4242,
        ), patch(
            "core_tools.provider.session_janitor._process_start_token",
            return_value=start,
        ), patch(
            "core_tools.provider.session_janitor.os.killpg",
        ) as killpg:
            code = _run_escalation(
                pgid=4242,
                status_fd=None,
                handshake_fd=None,
                go_fd=go_r,
                result_fd=result_w,
                agent_code=0,
                stop_requested=False,
                leader_pid=9999,
                leader_start=start,
            )
        killpg.assert_not_called()
        assert code == 1
    finally:
        for fd in (go_r, result_r, result_w):
            try:
                os.close(fd)
            except OSError:
                pass


def test_fallback_refuses_to_signal_caller_process_group() -> None:
    proc = MagicMock()
    proc.pid = os.getpid()
    proc.poll.return_value = None
    proc._core_tools_raw_poll = lambda: None
    with patch("core_tools.provider.process_identity.os.killpg") as killpg:
        status = _fallback_kill_bound_janitor_group(
            proc,
            pgid=os.getpgrp(),
            timeout=0.1,
        )
    killpg.assert_not_called()
    assert status["drain"] == DrainResult.UNVERIFIABLE.value
