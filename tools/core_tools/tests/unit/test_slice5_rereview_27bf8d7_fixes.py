"""Slice 5 rereview 27bf8d7: owned session proof, not PGID membership."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.process_cleanup import is_pid_alive, terminate_process_tree
from core_tools.provider.process_identity import (
    ProcessIdentity,
    capture_process_group_identities,
    read_process_identity,
)
from core_tools.provider.session_janitor import (
    DrainResult,
    _abandon_group_if_unresolved,
    _leader_still_owns_group,
    _signal_group,
)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_shared_pgid_regression_survives_in_outer_harness(tmp_path: Path) -> None:
    script = tmp_path / "shared_pgid_harness.py"
    script.write_text(
        textwrap.dedent(
            """
            import subprocess
            import sys
            import time
            from core_tools.provider.process_cleanup import terminate_process_tree

            sibling = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(17)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            target = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                time.sleep(0.05)
                terminate_process_tree(target, timeout=1.0)
                rc = sibling.wait(timeout=2.0)
                raise SystemExit(0 if rc == 17 else 2)
            finally:
                if target.poll() is None:
                    target.kill()
                    target.wait(timeout=2.0)
                if sibling.poll() is None:
                    sibling.kill()
                    sibling.wait(timeout=2.0)
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_foreign_same_pgid_process_is_neither_signaled_nor_reaped() -> None:
    foreign = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    owned = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "TDP_RUN_ID": "run-owned"},
    )
    try:
        time.sleep(0.05)
        assert os.getpgid(foreign.pid) == os.getpgid(owned.pid)
        terminate_process_tree(owned, timeout=1.0)
        assert foreign.poll() is None
        assert is_pid_alive(foreign.pid)
    finally:
        for proc in (owned, foreign):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2.0)


def test_capture_does_not_stamp_leader_run_id_on_foreign_member() -> None:
    leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-owned")
    observed_leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-owned")
    observed_foreign = ProcessIdentity(pid=5151, start_time="200", run_id=None)

    def fake_read(pid: int, *, run_id: str | None = None, command=None, timeout=None):
        if pid == 4242:
            return observed_leader
        return ProcessIdentity(pid=pid, start_time="200", run_id=run_id)

    with patch(
        "core_tools.provider.process_identity.read_process_identity",
        side_effect=fake_read,
    ), patch(
        "core_tools.provider.process_identity.read_process_group_id",
        return_value=99,
    ), patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[4242, 5151],
    ):
        captured = capture_process_group_identities(leader)

    assert captured is not None
    assert all(item.pid != 5151 or item.run_id is None for item in captured)
    assert captured == [leader] or all(item.pid != 5151 for item in captured)


def test_read_process_identity_observes_lineage_instead_of_caller_run_id() -> None:
    with patch(
        "core_tools.provider.process_identity.read_process_start_time",
        return_value="100",
    ), patch(
        "core_tools.provider.process_identity.read_process_run_id",
        return_value="run-observed",
    ), patch(
        "core_tools.provider.process_identity.read_process_owner_id",
        return_value="owner-observed",
    ):
        identity = read_process_identity(4242, run_id="run-caller")

    assert identity is not None
    assert identity.run_id == "run-observed"
    assert identity.owner_id == "owner-observed"


def test_signal_group_requires_sid_and_start_token() -> None:
    def fake_pgid(pid: int) -> int:
        return 1 if pid == 1 else 50

    with patch("core_tools.provider.session_janitor.os.killpg") as killpg, patch(
        "core_tools.provider.session_janitor.os.getpid", return_value=50
    ), patch(
        "core_tools.provider.session_janitor.os.getpgrp", return_value=50
    ), patch(
        "core_tools.provider.session_janitor.os.getppid", return_value=1
    ), patch(
        "core_tools.provider.session_janitor.os.getpgid", side_effect=fake_pgid
    ), patch(
        "core_tools.provider.session_janitor.os.getsid", return_value=99
    ), patch(
        "core_tools.provider.session_janitor._process_start_token",
        return_value="100.0",
    ):
        _signal_group(signal.SIGKILL)
    killpg.assert_not_called()


def test_unverifiable_abandon_does_not_killpg() -> None:
    with patch("core_tools.provider.session_janitor._signal_group") as signal_group:
        _abandon_group_if_unresolved(DrainResult.UNVERIFIABLE)
    signal_group.assert_not_called()


def test_unverifiable_handoff_does_not_promote_to_survivors_kill() -> None:
    from core_tools.provider.session_janitor import _complete_unresolved_cleanup

    with patch("core_tools.provider.session_janitor._signal_group") as signal_group:
        _complete_unresolved_cleanup(DrainResult.UNVERIFIABLE)
        _complete_unresolved_cleanup(None)
    signal_group.assert_not_called()


def test_leader_reject_prevents_later_fallback_killpg() -> None:
    start = "100.000001"
    go_r, go_w = os.pipe()
    result_r, result_w = os.pipe()
    os.write(go_w, b"GO\n")
    os.close(go_w)
    try:
        with patch(
            "core_tools.provider.session_janitor._leader_still_owns_group",
            return_value=False,
        ), patch(
            "core_tools.provider.session_janitor.os.killpg",
        ) as killpg:
            from core_tools.provider.session_janitor import _run_escalation

            code = _run_escalation(
                pgid=4242,
                status_fd=None,
                handshake_fd=None,
                go_fd=go_r,
                result_fd=result_w,
                agent_code=0,
                stop_requested=False,
                leader_pid=4242,
                leader_start=start,
            )
        killpg.assert_not_called()
        assert code == 1
        assert _leader_still_owns_group(4242, 9999, start) is False
    finally:
        for fd in (go_r, result_r, result_w):
            try:
                os.close(fd)
            except OSError:
                pass
