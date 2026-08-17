"""Slice 5 rereview 171505: agent-start bound, stdout EOF, fail-closed PGID, wait-dead."""

from __future__ import annotations

import inspect
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _SubprocessStdoutIterator,
    default_process_runner,
)
from core_tools.provider.errors import ProviderTurnStartupError
from core_tools.provider.process_cleanup import PidInspectState, ProcessGroupState
from core_tools.provider.process_identity import ProcessIdentity, _wait_identities_dead
from tests.conftest import tracked_turn_proc


def _idle_config(idle: float) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
                "agent_start_timeout_seconds": 0.2,
            }
        }
    }


def _provider(tmp_path: Path, idle: float = 0.08) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=default_process_runner,
        binary=str(agent),
        skip_probe=True,
    )


def test_wait_agent_started_eof_is_typed_startup_failure() -> None:
    started_r, started_w = os.pipe()
    os.close(started_w)
    iterator = _SubprocessStdoutIterator.__new__(_SubprocessStdoutIterator)
    iterator._started_read_fd = started_r
    iterator._agent_started = False
    iterator._proc = MagicMock()
    iterator._proc.poll.return_value = None
    iterator._proc.pid = os.getpid()
    with patch(
        "core_tools.provider.cursor.inspect_pid_liveness",
        return_value=PidInspectState.LIVE,
    ):
        with pytest.raises(ProviderTurnStartupError, match="failed to start"):
            iterator.wait_agent_started(timeout=0.3)
    iterator._close_started_fd()


def test_wait_agent_started_timeout_does_not_become_idle_stall(tmp_path: Path) -> None:
    script = (
        "import time\n"
        "time.sleep(30)\n"
    )
    provider = _provider(tmp_path, idle=0.08)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._set_collect_context(session_id, "planner")

    def hang_started(self, timeout=None):
        del timeout
        time.sleep(0.05)
        raise ProviderTurnStartupError("provider agent failed to start")

    gen = provider._wrap_runner(default_process_runner)(
        [sys.executable, "-c", script], tmp_path
    )
    with patch.object(_SubprocessStdoutIterator, "wait_agent_started", hang_started):
        started = time.monotonic()
        with pytest.raises(ProviderTurnStartupError, match="failed to start"):
            next(gen)
        assert time.monotonic() - started < 1.0
    try:
        gen.close()
    except Exception:
        pass


def test_late_child_pgid_stays_owned_after_janitor_and_identities_die(tmp_path: Path) -> None:
    from core_tools.provider.process_identity import (
        GroupLineageState,
        IdentityInspectState,
    )

    provider = _provider(tmp_path, idle=0.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(
        pid=4242, start_time="100", run_id="run-a", owner_id="owner-a"
    )
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.owner_id = "owner-a"
    entry.pgid = 4242
    entry.member_identities = (leader,)
    entry.proc = None
    entry.group_observed_gone = False
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.GONE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_janitor_source_does_not_raw_kill_enumerated_pids() -> None:
    from core_tools.provider import session_janitor as janitor

    source = inspect.getsource(janitor)
    assert "os.kill(pid," not in source
    assert "_kill_group_peers" not in source


def test_wait_dead_records_shrinking_identity_timeouts() -> None:
    identities = [ProcessIdentity(pid=index, start_time="1") for index in range(4)]
    seen: list[float | None] = []
    clock = {"t": 0.0}

    def fake_mono() -> float:
        return clock["t"]

    def fake_present(identity, timeout=None):
        del identity
        seen.append(timeout)
        clock["t"] += 0.04
        return True

    with patch(
        "core_tools.provider.process_identity._identity_still_present",
        side_effect=fake_present,
    ), patch(
        "core_tools.provider.process_identity.time.sleep",
        return_value=None,
    ), patch(
        "core_tools.provider.process_identity.time.monotonic",
        side_effect=fake_mono,
    ):
        assert _wait_identities_dead(identities, timeout=0.15) is False
    assert seen
    assert seen[0] is not None and seen[0] <= 0.15
    if len(seen) > 1:
        assert seen[-1] is not None
        assert seen[-1] <= seen[0]


def test_wait_dead_does_not_reset_global_deadline() -> None:
    identities = [ProcessIdentity(pid=index, start_time="1") for index in range(4)]
    seen: list[float | None] = []

    def fake_present(identity, timeout=None):
        del identity
        seen.append(timeout)
        time.sleep(0.04)
        return True

    started = time.monotonic()
    with patch(
        "core_tools.provider.process_identity._identity_still_present",
        side_effect=fake_present,
    ):
        assert _wait_identities_dead(identities, timeout=0.15) is False
    assert time.monotonic() - started <= 1.0
    assert seen[0] is not None and seen[0] <= 0.15
    if len(seen) > 1:
        assert seen[-1] is not None
        assert seen[-1] <= seen[0]
