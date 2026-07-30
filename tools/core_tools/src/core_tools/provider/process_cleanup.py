"""Process-tree termination helpers for provider subprocess cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any


def terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Terminate a subprocess and any descendants started in its process group."""

    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return

    pid = proc.pid
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            proc.terminate()
        except ProcessLookupError:
            return
    except PermissionError:
        proc.terminate()

    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
    except PermissionError:
        proc.kill()

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
