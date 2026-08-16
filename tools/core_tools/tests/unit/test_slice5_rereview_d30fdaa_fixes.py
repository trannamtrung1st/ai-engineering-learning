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

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    def slow_capture(*_args, timeout=None, **_kwargs):
        if timeout is None:
            time.sleep(0.2)
        return []

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    with patch(
        "core_tools.provider.process_identity.capture_process_group_identities",
        side_effect=slow_capture,
    ):
        handshake_done: dict[str, float] = {}
        original_wait = _SubprocessStdoutIterator.wait_agent_started

        def wait_then_idle(self, timeout=None):
            original_wait(self, timeout=timeout)
            handshake_done["t"] = time.monotonic()

        stalled_at: dict[str, float] = {}

        def mark_stall(*args, **kwargs):
            stalled_at.setdefault("t", time.monotonic())
            return True

        with patch.object(
            _SubprocessStdoutIterator,
            "wait_agent_started",
            wait_then_idle,
        ), patch(
            "core_tools.provider.cursor.terminate_process_tree",
            side_effect=mark_stall,
        ):
            session_id = provider.start_primary_session("planner", {"goal": "x"})
            with pytest.raises(ProviderTurnStalledError):
                list(provider.stream_events(session_id))
            assert stalled_at["t"] - handshake_done["t"] < idle + 0.1


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
