"""Ctrl+C / cancel must terminate the Cursor agent process."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from top_down_planning.cursor_client import CursorClient
from top_down_planning.errors import UserInterrupted


async def _wait_for_process_exit(pid: int, *, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"process {pid} did not exit after cancel")


@pytest.mark.asyncio
async def test_cancel_terminates_agent(
    fake_agent_bin: str,
    example_input: Path,
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "agent-timeout"
    wrapper.write_text(
        "#!/bin/sh\n"
        "export FAKE_AGENT_MODE=timeout\n"
        "export FAKE_AGENT_SLEEP=30\n"
        f"exec '{sys.executable}' '{fake_agent_bin}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    started: list[int] = []
    task = asyncio.create_task(
        client.run_session(
            workspace=tmp_path,
            prompt="plan",
            timeout_seconds=60,
            events_path=tmp_path / "events.ndjson",
            log_path=tmp_path / "session.log",
            on_agent_started=started.append,
        )
    )

    for _ in range(40):
        if started:
            break
        await asyncio.sleep(0.05)
    assert started, "agent never started"
    task.cancel()

    with pytest.raises(UserInterrupted, match="terminated") as exc_info:
        await task

    pid = exc_info.value.agent_pid
    assert pid == started[0]
    await _wait_for_process_exit(pid)
