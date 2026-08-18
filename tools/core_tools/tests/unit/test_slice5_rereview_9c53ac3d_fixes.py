"""Slice 5 rereview 9c53ac3d: iterator-tree test cleanup must killpg then raw-wait."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import pytest

from core_tools.provider.cursor import _SubprocessStdoutIterator
from tests.conftest import close_and_reap_iterator, wait_published_pid


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX session kill")
def test_close_and_reap_iterator_kills_descendants_and_raw_reaps_leader(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        iterator.wait_agent_started(timeout=2.0)
        child_pid = wait_published_pid(child_pid_file)
        assert child_pid is not None
        proc = iterator._proc
        os.kill(proc.pid, signal.SIGKILL)
    except BaseException:
        close_and_reap_iterator(iterator)
        raise
    close_and_reap_iterator(iterator)
    raw_poll = getattr(proc, "_core_tools_raw_poll", proc.poll)
    assert raw_poll() is not None
    with pytest.raises(OSError):
        os.kill(child_pid, 0)
