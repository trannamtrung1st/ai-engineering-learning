"""Slice 5 rereview 220bbcb9: historical presence uses one inspect per identity."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import (
    ProviderLifecycleTimeoutError,
    ProviderSessionTerminationError,
)
from core_tools.provider.process_cleanup import PidInspectState, ProcessGroupState
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
)
from tests.conftest import tracked_turn_proc


def _provider(tmp_path: Path) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent),
        skip_probe=True,
    )


def _tracked(provider: CursorProvider, *, pgid: int = 4242):
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(
        pid=pgid, start_time="100", run_id="run-a", owner_id="owner-a"
    )
    proc = MagicMock()
    proc.pid = pgid
    proc.poll.return_value = 1
    provider._tracked_turn_procs[pgid] = tracked_turn_proc(session_id, "planner", pgid)
    entry = provider._tracked_turn_procs[pgid]
    entry.proc = proc
    entry.identity = leader
    entry.pgid = pgid
    entry.member_identities = (leader,)
    entry.owner_id = "owner-a"
    return session_id, entry


def test_historical_presence_does_not_reinspect_leader_after_gone(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    _session_id, entry = _tracked(provider)
    calls: list[float | None] = []

    def inspect(identity, timeout=None):
        del identity
        calls.append(timeout)
        return IdentityInspectState.GONE

    live_calls: list[object] = []

    def live(identity, timeout=None):
        live_calls.append(timeout)
        del identity
        return False

    with patch(
        "core_tools.provider.cursor.inspect_process_identity",
        side_effect=inspect,
    ), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        side_effect=live,
    ):
        present = provider._historical_identities_still_present(entry, timeout=0.05)
    assert present is False
    assert len(calls) == 1
    assert calls[0] is not None and calls[0] <= 0.05 + 1e-6
    assert live_calls == []


def test_duplicate_leader_in_members_uses_one_identity_inspection(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    _session_id, entry = _tracked(provider)
    child = ProcessIdentity(pid=5151, start_time="200", run_id="run-a", owner_id="owner-a")
    entry.member_identities = (entry.identity, entry.identity, child)
    inspected: list[int] = []

    def inspect(identity, timeout=None):
        del timeout
        inspected.append(identity.pid)
        return IdentityInspectState.GONE

    with patch(
        "core_tools.provider.cursor.inspect_process_identity",
        side_effect=inspect,
    ):
        provider._historical_identities_still_present(entry, timeout=0.05)
    assert inspected.count(4242) == 1
    assert inspected.count(5151) == 1


def test_terminate_session_slow_identity_inspect_stays_within_timeout(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id, _entry = _tracked(provider)
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    def slow_inspect(identity, timeout=None):
        del identity
        budget = 0.05 if timeout is None else max(0.0, timeout)
        clock["t"] += min(0.04, budget)
        return IdentityInspectState.GONE

    with patch("core_tools.provider.cursor.time.monotonic", fake_monotonic), patch(
        "core_tools.provider.process_identity.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.process_cleanup.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        side_effect=slow_inspect,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.GONE,
    ), patch(
        "core_tools.provider.cursor.CursorProvider.abort_turn",
    ), patch(
        "core_tools.provider.cursor.CursorProvider.wait_turn_settled",
    ):
        try:
            provider.terminate_session(session_id, timeout=0.05)
        except (ProviderSessionTerminationError, ProviderLifecycleTimeoutError):
            pass
    assert clock["t"] <= 0.05 + 1e-6


def test_historical_presence_darwin_liveness_probe_uses_one_budget(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    _session_id, entry = _tracked(provider)
    timeouts: list[float | None] = []
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    def slow_liveness(pid, timeout=None):
        del pid
        timeouts.append(timeout)
        clock["t"] += 0.03
        return PidInspectState.GONE

    with patch("core_tools.provider.process_identity.sys.platform", "darwin"), patch(
        "core_tools.provider.process_cleanup.sys.platform",
        "darwin",
    ), patch(
        "core_tools.provider.process_identity.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.cursor.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.process_identity.inspect_pid_liveness",
        side_effect=slow_liveness,
    ):
        provider._historical_identities_still_present(entry, timeout=0.05)
    assert timeouts
    assert all(t is not None and t <= 0.05 + 1e-6 for t in timeouts)
    assert len(timeouts) == 1
    assert clock["t"] == 0.03
