"""Slice 5 rereview ff20bb4: nested identity deadline and one-shot process capture."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    _wait_identities_dead,
    inspect_process_identity,
)


def _idle_config() -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": 2.0,
                "max_retries_per_call": 0,
            }
        }
    }


def test_inspect_identity_passes_remaining_budget_to_read() -> None:
    identity = ProcessIdentity(pid=7, start_time="1")
    seen: list[float | None] = []

    def fake_liveness(pid, timeout=None):
        del pid
        seen.append(timeout)
        import time

        time.sleep(0.05)
        from core_tools.provider.process_cleanup import PidInspectState

        return PidInspectState.LIVE

    def fake_read(pid, run_id=None, command=None, timeout=None):
        del pid, run_id, command
        seen.append(timeout)
        return identity

    with patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        side_effect=fake_liveness,
    ), patch(
        "core_tools.provider.process_identity.read_process_identity",
        side_effect=fake_read,
    ):
        assert inspect_process_identity(identity, timeout=0.2) is IdentityInspectState.LIVE_MATCH
    assert seen[0] is not None and seen[0] <= 0.2
    assert seen[1] is not None
    assert seen[1] <= seen[0] - 0.03


def test_wait_dead_records_shrinking_timeouts_without_wall_clock_slack() -> None:
    identities = [ProcessIdentity(pid=index, start_time="1") for index in range(4)]
    seen: list[float | None] = []

    def fake_any(targets, timeout=None):
        del targets
        seen.append(timeout)
        return True

    with patch(
        "core_tools.provider.process_identity._any_identities_still_alive",
        side_effect=fake_any,
    ), patch(
        "core_tools.provider.process_identity.time.sleep",
        return_value=None,
    ), patch(
        "core_tools.provider.process_identity.time.monotonic",
        side_effect=[0.0, 0.0, 0.04, 0.04, 0.08, 0.08, 0.12, 0.12, 0.16, 0.16, 0.20],
    ):
        assert _wait_identities_dead(identities, timeout=0.15) is False
    assert seen
    assert seen[0] is not None and seen[0] <= 0.15
    if len(seen) > 1:
        assert seen[-1] is not None
        assert seen[-1] <= seen[0]


def test_stream_registers_tracked_process_once(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": str(i)}]}})
        for i in range(100)
    ]
    init = json.dumps(
        {"type": "system", "subtype": "init", "session_id": "chat-once"}
    )
    script = (
        "import sys\n"
        f"print({init!r}, flush=True)\n"
        + "".join(f"print({line!r}, flush=True)\n" for line in lines)
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    with patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        return_value=[],
    ) as captured:
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        list(provider.stream_events(session_id))
        assert captured.call_count == 1
