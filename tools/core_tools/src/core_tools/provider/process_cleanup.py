"""Process-tree termination helpers for provider subprocess cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_pid_tree(pid: int) -> bool:
    """Terminate a process and any descendants started in its process group.

    Returns True when the PID is confirmed dead after termination attempts.
    """

    if not is_pid_alive(pid):
        return True

    if sys.platform == "win32":
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not is_pid_alive(pid)
        _wait_pid(pid, timeout=5)
        if is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                return not is_pid_alive(pid)
            _wait_pid(pid, timeout=5)
        return not is_pid_alive(pid)

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return not is_pid_alive(pid)
    except PermissionError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not is_pid_alive(pid)

    if _wait_pid(pid, timeout=5):
        return True

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return not is_pid_alive(pid)
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return not is_pid_alive(pid)

    _wait_pid(pid, timeout=5)
    return not is_pid_alive(pid)


def _wait_pid(pid: int, *, timeout: float) -> bool:
    deadline = timeout
    interval = 0.05
    while deadline > 0 and is_pid_alive(pid):
        try:
            waited_pid, _status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                return True
        except ChildProcessError:
            return not is_pid_alive(pid)
        except OSError:
            break
        import time

        time.sleep(min(interval, deadline))
        deadline -= interval
    return not is_pid_alive(pid)


def terminate_process_tree(proc: subprocess.Popen[Any]) -> bool:
    """Terminate a subprocess and return True when the PID is confirmed dead."""

    if proc.poll() is not None:
        return True

    if sys.platform == "win32":
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return proc.poll() is not None

    pid = proc.pid
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            proc.terminate()
        except ProcessLookupError:
            return not is_pid_alive(pid)
    except PermissionError:
        proc.terminate()

    try:
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        try:
            proc.kill()
        except ProcessLookupError:
            return not is_pid_alive(pid)
    except PermissionError:
        proc.kill()

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    return proc.poll() is not None and not is_pid_alive(pid)
