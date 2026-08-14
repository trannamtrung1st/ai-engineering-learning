"""Slice 5 eighteenth re-review regressions (S5-RR18-001 through S5-RR18-006)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc, default_process_runner
from core_tools.provider.process_cleanup import ProcessGroupState, is_pid_alive
from core_tools.provider.process_identity import ProcessIdentity
from core_tools.provider.session_janitor import DrainResult, janitor_command


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


def _wait_pid_file(path: Path, timeout: float = 2.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.02)
    raise AssertionError(f"pid file was not written: {path}")


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_peer_pids_is_empty_for_session_leader_with_no_children() -> None:
    janitor_path = Path(
        __import__("core_tools.provider.session_janitor", fromlist=["janitor_command"]).__file__
    ).resolve()
    provider_dir = str(janitor_path.parent)
    script = (
        "import json, sys\n"
        f"sys.path.insert(0, {provider_dir!r})\n"
        "import session_janitor as janitor\n"
        "janitor._peer_pids()\n"
        "sys.stdout.write(json.dumps(janitor._peer_pids()))\n"
        "sys.stdout.flush()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    out, err = proc.communicate(timeout=5)
    assert proc.returncode == 0, err
    assert json.loads(out) == []


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_no_descendant_janitor_cleanup_is_faster_than_drain_budget() -> None:
    started = time.monotonic()
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", "import sys; sys.exit(0)"]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    stdout, stderr = proc.communicate(timeout=3)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, stderr
    assert elapsed < 2.0


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_sigterm_accepting_child_finishes_before_kill_phase(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.exit(0)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    child_pid = _wait_pid_file(child_pid_file)
    started = time.monotonic()
    stdout, stderr = proc.communicate(timeout=3)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, stderr
    assert elapsed < 2.0
    assert is_pid_alive(child_pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_sigterm_ignoring_child_escalates_only_when_needed(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.exit(0)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    child_pid = _wait_pid_file(child_pid_file)
    started = time.monotonic()
    time.sleep(0.1)
    assert proc.poll() is None
    assert is_pid_alive(child_pid) is True
    stdout, stderr = proc.communicate(timeout=12)
    elapsed = time.monotonic() - started
    assert is_pid_alive(child_pid) is False
    assert elapsed >= 0.4
    assert elapsed < 12.0
    assert proc.returncode in {0, -signal.SIGKILL}


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_drain_does_not_signal_unrelated_replacement_process(tmp_path: Path) -> None:
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        script = (
            "import os, sys, time\n"
            "child = os.fork()\n"
            "if child == 0:\n"
            "    time.sleep(60)\n"
            "    os._exit(0)\n"
            "sys.exit(0)\n"
        )
        proc = subprocess.Popen(
            janitor_command([sys.executable, "-c", script]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=True,
        )
        proc.communicate(timeout=3)
        assert unrelated.poll() is None
    finally:
        if unrelated.poll() is None:
            unrelated.kill()
            unrelated.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_unverifiable_peer_scan_does_not_report_agent_success() -> None:
    from tests.unit.test_slice5_rereview19_fixes import _read_status_fd, _spawn_hooked_janitor

    proc, status_r = _spawn_hooked_janitor([sys.executable, "-c", "import sys; sys.exit(0)"])
    time.sleep(0.2)
    proc.wait(timeout=3)
    status = _read_status_fd(status_r)
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert status["agent_code"] == 0
    assert proc.returncode in {0, -signal.SIGKILL}


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_stop_path_is_bounded_when_agent_ignores_term_and_scan_fails(
    tmp_path: Path,
) -> None:
    from tests.unit.test_slice5_rereview19_fixes import (
        _read_status_fd,
        _spawn_hooked_janitor,
        _wait_pid_file,
    )

    agent_pid_file = tmp_path / "agent.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(agent_pid_file)!r}, 'w', encoding='utf-8').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    proc, status_r = _spawn_hooked_janitor([sys.executable, "-c", script])
    agent_pid = _wait_pid_file(agent_pid_file)
    started = time.monotonic()
    assert proc.stdin is not None
    proc.stdin.write("STOP\n")
    proc.stdin.close()
    proc.wait(timeout=4)
    elapsed = time.monotonic() - started
    status = _read_status_fd(status_r)
    assert elapsed < 4.0
    assert status is not None
    assert status["drain"] == DrainResult.CLEAN.value
    assert is_pid_alive(agent_pid) is False
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=2)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_control_pipe_eof_terminates_agent_and_descendants(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.stdout.write('ready\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert "ready" in line
    child_pid = _wait_pid_file(child_pid_file)
    started = time.monotonic()
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait(timeout=4)
    elapsed = time.monotonic() - started
    assert elapsed < 4.0
    assert is_pid_alive(child_pid) is False
    assert proc.poll() is not None


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_proxy_preserves_final_records_when_descendant_holds_pipe(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    last = '{"type":"result","subtype":"success","session_id":"sess-final"}'
    script = (
        "import os, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "for index in range(20):\n"
        "    sys.stdout.write(f'line-{index}\\n')\n"
        f"sys.stdout.write({last!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"
    )
    started = time.monotonic()
    lines = list(default_process_runner([sys.executable, "-c", script], tmp_path))
    elapsed = time.monotonic() - started
    child_pid = _wait_pid_file(child_pid_file)
    assert elapsed < 3.0
    assert last in lines
    assert "line-0" in lines
    assert is_pid_alive(child_pid) is False


def test_group_gone_ack_prevents_treating_reused_pgid_as_owned(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=default_process_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._set_collect_context(session_id, "planner")
    with patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        lines = list(
            provider._runner(
                [sys.executable, "-c", "print('done', flush=True)"],
                tmp_path,
            )
        )
        assert "done" in lines
        assert provider._session_has_surviving_pids(session_id) is False
        tracked = list(provider._tracked_turn_procs.values())
        assert all(
            not provider._tracked_tree_is_live(entry) for entry in tracked
        )


def test_clean_ack_marks_original_group_gone_before_pgid_reuse(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    entry = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader,),
        group_observed_gone=True,
    )
    provider._tracked_turn_procs[4242] = entry
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.LIVE,
        ):
            assert provider._tracked_tree_is_live(entry) is False
            provider.reconcile_terminated_pids([4242])
    assert 4242 not in provider._tracked_turn_procs
    assert provider.list_active_sessions() == []
