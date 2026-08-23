"""Shared pytest helpers for core_tools tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import _TrackedTurnProc
from core_tools.provider.process_identity import ProcessIdentity
from core_tools.provider.session_janitor import (
    _KILL_DRAIN_SECONDS,
    _TERM_DRAIN_SECONDS,
)

# Janitor cleanup can spend SIGTERM drain then SIGKILL drain before exiting.
_LEFTOVER_SETTLE_SECONDS = _TERM_DRAIN_SECONDS + _KILL_DRAIN_SECONDS + 1.0


def _kill_session_and_raw_wait(
    proc: subprocess.Popen[str],
    extra_pids: tuple[int, ...] = (),
) -> None:
    """SIGKILL the bound session group, then consume the leader's raw wait status."""

    pgid = getattr(proc, "_core_tools_session_pgid", None)
    if pgid is None and proc.pid:
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = proc.pid
    if pgid is not None:
        try:
            os.killpg(int(pgid), signal.SIGKILL)
        except OSError:
            pass
    for pid in extra_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    raw_wait = getattr(proc, "_core_tools_raw_wait", proc.wait)
    try:
        raw_wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    for pid in extra_pids:
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)


def close_and_reap_iterator(iterator) -> None:
    """Kill a bound iterator's process group, close pipes, and raw-reap the leader."""

    proc = getattr(iterator, "_proc", None)
    pgid = None
    if proc is not None:
        pgid = getattr(proc, "_core_tools_session_pgid", None)
        if pgid is None and proc.pid:
            try:
                pgid = os.getpgid(proc.pid)
            except OSError:
                pgid = proc.pid
        if pgid is not None:
            try:
                os.killpg(int(pgid), signal.SIGKILL)
            except OSError:
                pass
    try:
        iterator.close()
    except Exception:
        pass
    if proc is None:
        return
    raw_wait = getattr(proc, "_core_tools_raw_wait", proc.wait)
    try:
        raw_wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def tracked_turn_proc(
    session_id: str,
    role: str,
    pid: int,
    *,
    proc: subprocess.Popen | None = None,
    start_time: str = "100",
    run_id: str | None = None,
) -> _TrackedTurnProc:
    from core_tools.provider.process_cleanup import read_process_group_id
    from core_tools.provider.process_identity import (
        capture_process_group_identities,
        read_process_identity,
    )

    identity = ProcessIdentity(pid=pid, start_time=start_time, run_id=run_id)
    if proc is not None:
        live_identity = read_process_identity(proc.pid, run_id=run_id)
        if live_identity is not None:
            identity = live_identity
    pgid = read_process_group_id(pid) if proc is not None else None
    members: tuple[ProcessIdentity, ...] | None = None
    if proc is not None and identity is not None:
        captured = capture_process_group_identities(identity)
        if captured is not None:
            members = tuple(captured)
    return _TrackedTurnProc(
        session_id=session_id,
        role=role,
        proc=proc,
        identity=identity,
        pgid=pgid,
        member_identities=members,
    )


def spawn_sigterm_ignoring_leader_with_child(
    tmp_path: Path,
) -> tuple[subprocess.Popen[str], int]:
    """Start a leader that ignores SIGTERM and forks a sleeping child."""

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
    from core_tools.provider.session_janitor import janitor_command

    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    child_pid = wait_published_pid(child_pid_file)
    if child_pid is None:
        reap_process_group(proc)
        raise AssertionError("child PID file was not written")
    return proc, child_pid


def wait_published_pid(path: Path, *, attempts: int = 40) -> int | None:
    """Return a PID once *path* contains a complete integer, else ``None``."""

    for _ in range(attempts):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if text.isdigit():
            return int(text)
        time.sleep(0.05)
    return None


def reap_process_group(
    proc: subprocess.Popen[str],
    extra_pids: tuple[int, ...] = (),
) -> None:
    """SIGKILL the spawned session and any known descendants, then raw-wait."""

    _kill_session_and_raw_wait(proc, extra_pids=extra_pids)


def spawn_hold_process() -> subprocess.Popen[bytes]:
    """Start a child that holds until stdin EOF or SIGKILL — not a timed sleep."""

    return subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )


def reap_hold_process(proc: subprocess.Popen[bytes]) -> None:
    """Guarantee a hold child is dead, even if the test failed mid-assertion."""

    if proc.poll() is not None:
        return
    if sys.platform != "win32" and proc.pid:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _signal_leftover_python_descendants(leftover: dict[int, str]) -> None:
    """SIGKILL leftover test children (and their groups) so session teardown can finish."""

    for pid in leftover:
        if sys.platform != "win32":
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    _reap_unwaited_children()


def _python_descendant_pids(root_pid: int) -> dict[int, str]:
    output = subprocess.check_output(
        ["ps", "-axww", "-o", "pid=,ppid=,state=,command="],
        text=True,
    )
    by_parent: dict[int, list[int]] = {}
    commands: dict[int, str] = {}
    states: dict[int, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        states[pid] = parts[2]
        commands[pid] = parts[3] if len(parts) > 3 else ""
        by_parent.setdefault(ppid, []).append(pid)
    found: dict[int, str] = {}
    stack = list(by_parent.get(root_pid, ()))
    while stack:
        pid = stack.pop()
        ps_cmd = commands.get(pid, "")
        cmd = _process_command(pid) or ps_cmd
        if _ignore_leftover_python_descendant(
            cmd,
            pid=pid,
            ps_cmd=ps_cmd,
            ps_state=states.get(pid, ""),
        ):
            stack.extend(by_parent.get(pid, ()))
            continue
        if "python" in cmd.lower():
            found[pid] = cmd
        stack.extend(by_parent.get(pid, ()))
    return found


def _process_command(pid: int) -> str:
    proc_cmd = Path(f"/proc/{pid}/cmdline")
    if proc_cmd.exists():
        try:
            return proc_cmd.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            return ""
    return ""


def _is_pytest_infrastructure(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(
        token in lowered
        for token in (
            "resource_tracker",
            "forkserver",
            "semaphore_tracker",
            "execnet",
            "multiprocessing.spawn",
            "spawn_main",
        )
    )


def _linux_stat_is_zombie(pid: int) -> bool:
    """Return whether ``/proc/<pid>/stat`` reports an unreaped zombie."""

    path = Path(f"/proc/{pid}/stat")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    right_paren = text.rfind(")")
    if right_paren == -1:
        return False
    fields = text[right_paren + 2 :].split()
    return bool(fields) and fields[0][:1] == "Z"


def _ignore_leftover_python_descendant(
    cmd: str,
    pid: int | None = None,
    ps_cmd: str = "",
    ps_state: str = "",
) -> bool:
    """Ignore pytest helpers and already-dead zombies still visible in ``ps``."""

    if "<defunct>" in cmd.lower() or "<defunct>" in ps_cmd.lower():
        return True
    if str(ps_state).lstrip()[:1].upper() == "Z":
        return True
    if pid is not None and _linux_stat_is_zombie(pid):
        return True
    return _is_pytest_infrastructure(cmd)


def _reap_unwaited_children() -> None:
    waitpid = getattr(os, "waitpid", None)
    if waitpid is None:
        return
    while True:
        try:
            pid, _status = waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        except OSError:
            return
        if pid <= 0:
            return


def _open_fds() -> set[int]:
    proc_fd = Path("/proc/self/fd")
    if proc_fd.exists():
        names = os.listdir(proc_fd)
    else:
        names = os.listdir("/dev/fd")
    fds: set[int] = set()
    for name in names:
        try:
            fds.add(int(name))
        except ValueError:
            continue
    return fds


def _cursor_turn_enrich_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "cursor-turn-enrich" and thread.is_alive()
    ]


@pytest.fixture(autouse=True)
def assert_no_cursor_turn_enrich_threads():
    yield
    leftover = _cursor_turn_enrich_threads()
    deadline = time.monotonic() + 0.5
    while leftover and time.monotonic() < deadline:
        for thread in leftover:
            thread.join(timeout=0.05)
        leftover = _cursor_turn_enrich_threads()
    assert leftover == [], leftover


@pytest.fixture(autouse=True)
def trace_process_signals(monkeypatch: pytest.MonkeyPatch):
    if os.environ.get("TDP_TRACE_PROCESS_SIGNALS") != "1":
        yield
        return
    self_pid = os.getpid()
    try:
        self_pgrp = os.getpgrp()
    except OSError:
        self_pgrp = None
    print(
        f"[tdp-signal-trace] tester pid={self_pid} pgrp={self_pgrp}",
        file=sys.stderr,
        flush=True,
    )
    real_kill = os.kill
    real_killpg = os.killpg

    def traced_kill(pid: int, sig: int) -> None:
        print(
            f"[tdp-signal-trace] kill pid={pid} sig={sig} from pid={self_pid}",
            file=sys.stderr,
            flush=True,
        )
        real_kill(pid, sig)

    def traced_killpg(pgid: int, sig: int) -> None:
        print(
            f"[tdp-signal-trace] killpg pgid={pgid} sig={sig} from pid={self_pid} pgrp={self_pgrp}",
            file=sys.stderr,
            flush=True,
        )
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "kill", traced_kill)
    monkeypatch.setattr(os, "killpg", traced_killpg)
    yield


@pytest.fixture(scope="session", autouse=True)
def assert_no_leftover_python_descendants():
    parent = os.getpid()
    before = set(_python_descendant_pids(parent))
    yield
    leftover: dict[int, str] = {}
    deadline = time.monotonic() + _LEFTOVER_SETTLE_SECONDS
    while True:
        _reap_unwaited_children()
        leftover = {
            pid: cmd
            for pid, cmd in _python_descendant_pids(parent).items()
            if pid not in before
        }
        if not leftover or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if leftover:
        _signal_leftover_python_descendants(leftover)
        reap_deadline = time.monotonic() + 1.0
        while leftover and time.monotonic() < reap_deadline:
            leftover = {
                pid: cmd
                for pid, cmd in _python_descendant_pids(parent).items()
                if pid not in before
            }
            if leftover:
                _signal_leftover_python_descendants(leftover)
            time.sleep(0.05)
    assert leftover == {}, leftover
