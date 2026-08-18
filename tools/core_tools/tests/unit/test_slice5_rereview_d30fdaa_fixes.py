"""Slice 5 rereview d30fdaa: idle-budget tracking and fake-clock aggregate deadlines."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.errors import ProviderTurnStalledError
from core_tools.provider.process_identity import ProcessIdentity, _any_identities_still_alive
from tests.conftest import close_and_reap_iterator


def _idle_config(idle: float) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
            }
        }
    }


def test_slow_group_capture_does_not_extend_idle_timeout(tmp_path: Path) -> None:
    idle = 0.08
    script = "import time\ntime.sleep(60)\n"
    clock = {"t": 10.0}
    handshake_done: dict[str, float] = {}
    seen_deadline: dict[str, float | None] = {}
    stall_clock: dict[str, float] = {}

    def fake_monotonic() -> float:
        return clock["t"]

    holder: dict[str, _SubprocessStdoutIterator] = {}

    def runner(argv: list[str], cwd: Path):
        del argv
        iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)
        holder["it"] = iterator
        return iterator

    def slow_capture(*_args, timeout=None, **_kwargs):
        del timeout
        clock["t"] += 0.25
        return []

    def wait_then_idle(self, timeout=None):
        del self, timeout
        handshake_done["t"] = clock["t"]

    def fake_read_nonempty_line(self, timeout: float):
        del self
        clock["t"] += max(0.0, timeout)
        return None

    real_iter = CursorProvider._iter_stream_with_idle_timeout

    def recording_iter(*args, idle_timeout, on_idle, session_id=None, deadline=None):
        stream = args[-1]
        seen_deadline["value"] = deadline
        seen_deadline["wrap_mono"] = clock["t"]
        return real_iter(
            stream,
            idle_timeout=idle_timeout,
            on_idle=on_idle,
            session_id=session_id,
            deadline=deadline,
        )

    def mark_stall(*args, **kwargs):
        del args, kwargs
        stall_clock.setdefault("t", clock["t"])
        return True

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    try:
        with patch(
            "core_tools.provider.cursor.time.monotonic",
            fake_monotonic,
        ), patch(
            "core_tools.provider.process_identity.capture_process_group_identities",
            side_effect=slow_capture,
        ), patch.object(
            _SubprocessStdoutIterator,
            "wait_agent_started",
            wait_then_idle,
        ), patch.object(
            _SubprocessStdoutIterator,
            "read_nonempty_line",
            fake_read_nonempty_line,
        ), patch.object(
            CursorProvider,
            "_iter_stream_with_idle_timeout",
            recording_iter,
        ), patch(
            "core_tools.provider.cursor.terminate_process_tree",
            side_effect=mark_stall,
        ):
            session_id = provider.start_primary_session("planner", {"goal": "x"})
            with pytest.raises(ProviderTurnStalledError):
                list(provider.stream_events(session_id))
    finally:
        iterator = holder.get("it")
        if iterator is not None:
            close_and_reap_iterator(iterator)

    assert seen_deadline["value"] == pytest.approx(seen_deadline["wrap_mono"] + idle)
    assert stall_clock["t"] == pytest.approx(seen_deadline["value"])
    assert handshake_done["t"] <= seen_deadline["wrap_mono"]


def test_aggregate_identity_deadline_shrinks_without_wall_clock() -> None:
    identities = [ProcessIdentity(pid=index, start_time="1") for index in range(10)]
    seen: list[float | None] = []
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    def fake_alive(identity, timeout=None):
        del identity
        seen.append(timeout)
        if timeout is not None and timeout <= 0:
            return False
        clock["t"] += 0.03
        return False

    with patch(
        "core_tools.provider.process_identity.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.process_identity._identity_still_alive",
        side_effect=fake_alive,
    ):
        assert _any_identities_still_alive(identities, timeout=0.2) is False
    assert seen[0] is not None and seen[0] <= 0.2
    assert seen[-1] is not None
    assert seen[-1] < seen[0]
    assert seen[-1] <= 0.05
