"""Janitor startup/cancel cycles must not close FDs they do not own."""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

import pytest

from core_tools.provider.cursor import _SubprocessStdoutIterator
from tests.conftest import _open_fds


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX janitor FDs")
def test_janitor_startup_cancel_finalize_does_not_close_foreign_fds(tmp_path: Path) -> None:
    sentinel = os.dup(1)
    try:
        before = _open_fds()
        assert sentinel in before
        for _ in range(3):
            iterator = _SubprocessStdoutIterator(
                [sys.executable, "-c", "import time; time.sleep(8)"],
                tmp_path,
            )
            proc = iterator._proc
            iterator.close()
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, 9)
                except OSError:
                    pass
                raw_wait = getattr(proc, "_core_tools_raw_wait", proc.wait)
                raw_wait(timeout=2)
        after = _open_fds()
        disappeared = before - after
        assert sentinel not in disappeared
        assert not disappeared & {0, 1, 2}
        fcntl.fcntl(sentinel, fcntl.F_GETFD)
    finally:
        os.close(sentinel)
