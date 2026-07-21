"""Ctrl+C / cancel must terminate the Cursor agent process."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from todos_tool.cursor_client import CursorClient
from todos_tool.errors import UserInterrupted


def _stop_pid(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


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
    fake_agent: Path, git_project: Path, tmp_path: Path
) -> None:
    wrapper = tmp_path / "agent-timeout"
    wrapper.write_text(
        "#!/bin/sh\n"
        "export FAKE_AGENT_MODE=timeout\n"
        "export FAKE_AGENT_SLEEP=30\n"
        f"exec '{sys.executable}' '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    events_path = tmp_path / "events.ndjson"
    log_path = tmp_path / "session.log"
    started: list[int] = []

    task = asyncio.create_task(
        client.run_session(
            workspace=git_project,
            prompt="hi",
            phase="work",
            timeout_seconds=60,
            events_path=events_path,
            log_path=log_path,
            on_agent_started=started.append,
        )
    )

    for _ in range(40):
        if started:
            break
        await asyncio.sleep(0.05)
    assert started, "agent never started"
    task.cancel()

    with pytest.raises(UserInterrupted) as exc_info:
        await task

    pid = exc_info.value.agent_pid
    assert pid is not None
    assert pid == started[0]
    await _wait_for_process_exit(pid)


@pytest.mark.asyncio
async def test_timeout_still_terminates_agent(
    fake_agent: Path, git_project: Path, tmp_path: Path
) -> None:
    from todos_tool.errors import CursorSessionError

    wrapper = tmp_path / "agent-timeout-kill"
    wrapper.write_text(
        "#!/bin/sh\n"
        "export FAKE_AGENT_MODE=timeout\n"
        "export FAKE_AGENT_SLEEP=30\n"
        f"exec '{sys.executable}' '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    started: list[int] = []
    with pytest.raises(CursorSessionError, match="timed out"):
        await client.run_session(
            workspace=git_project,
            prompt="hi",
            phase="work",
            timeout_seconds=1,
            events_path=tmp_path / "events.ndjson",
            log_path=tmp_path / "session.log",
            on_agent_started=started.append,
        )
    assert started
    pid = started[0]
    dead = False
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            dead = True
            break
        await asyncio.sleep(0.05)
    if not dead:
        _stop_pid(pid)
