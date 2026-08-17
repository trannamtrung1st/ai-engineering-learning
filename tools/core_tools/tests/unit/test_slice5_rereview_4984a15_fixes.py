"""Slice 5 rereview 4984a15: ownerless PGID, fallback CLEAN, one lineage deadline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
    _fallback_kill_bound_janitor_group,
    current_process_group_lineage,
)
from core_tools.provider.session_janitor import DrainResult
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


def _ownerless_mismatch_entry(tmp_path: Path):
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.owner_id = None
    entry.member_identities = (leader,)
    entry.pgid = 4242
    entry.proc = None
    entry.group_observed_gone = False
    return provider, entry


def test_ownerless_mismatch_does_not_pin_live_numeric_pgid(tmp_path: Path) -> None:
    provider, entry = _ownerless_mismatch_entry(tmp_path)
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.IDENTITY_MISMATCH,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ):
        assert provider._tracked_tree_is_live(entry) is False


def test_ownerless_live_janitor_handle_still_owns_late_child(tmp_path: Path) -> None:
    provider, entry = _ownerless_mismatch_entry(tmp_path)
    proc = type("Proc", (), {"poll": lambda self: None, "pid": 4242})()
    entry.proc = proc
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_mismatch_with_owner_token_keeps_verified_current_owner(tmp_path: Path) -> None:
    provider, entry = _ownerless_mismatch_entry(tmp_path)
    entry.owner_id = "owner-a"
    entry.identity = ProcessIdentity(
        pid=4242, start_time="100", run_id="run-a", owner_id="owner-a"
    )
    entry.member_identities = (entry.identity,)
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.IDENTITY_MISMATCH,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_fallback_group_gone_is_not_clean_without_output_handoff() -> None:
    class ExitedProc:
        pid = 4242

        def poll(self) -> int:
            return 0

        def _core_tools_raw_poll(self) -> int:
            return 0

    with patch("core_tools.provider.process_identity.os.killpg") as killpg, patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[],
    ), patch(
        "core_tools.provider.process_identity.is_pid_alive",
        return_value=False,
    ):
        status = _fallback_kill_bound_janitor_group(ExitedProc(), pgid=4242, timeout=0.1)
    assert killpg.call_count == 0
    assert status["drain"] != DrainResult.CLEAN.value


def test_lineage_reads_each_member_environment_once() -> None:
    members = [
        ProcessIdentity(pid=11, start_time="1"),
        ProcessIdentity(pid=12, start_time="2"),
    ]
    calls: list[int] = []

    def fake_env(pid: int, *, timeout: float | None = None):
        del timeout
        calls.append(pid)
        return {"TDP_PROVIDER_OWNER_ID": "owner-a", "TDP_RUN_ID": "run-a"}

    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=members,
    ), patch(
        "core_tools.provider.process_identity._tdp_env_for_pid",
        fake_env,
    ):
        state = current_process_group_lineage(
            99, expected_run_id="run-z", expected_owner_id="owner-a", timeout=0.2
        )
    assert state is GroupLineageState.OWNED
    assert calls == [11, 12]


def test_lineage_obeys_one_aggregate_deadline() -> None:
    members = [
        ProcessIdentity(pid=pid, start_time=str(pid)) for pid in range(10, 15)
    ]
    clock = {"t": 100.0}
    budgets: list[float | None] = []

    def fake_monotonic() -> float:
        return clock["t"]

    def slow_env(pid: int, *, timeout: float | None = None):
        del pid
        budgets.append(timeout)
        budget = 0.2 if timeout is None else max(0.0, timeout)
        clock["t"] += min(0.05, budget)
        return {}

    with patch(
        "core_tools.provider.process_identity.time.monotonic",
        fake_monotonic,
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=members,
    ), patch(
        "core_tools.provider.process_identity._tdp_env_for_pid",
        slow_env,
    ):
        current_process_group_lineage(
            99, expected_run_id="run-a", expected_owner_id="owner-a", timeout=0.08
        )
    assert budgets
    assert budgets[0] == pytest.approx(0.08, abs=0.001)
    assert budgets[-1] is not None
    assert budgets[-1] < budgets[0]
    assert all(
        later is not None and earlier is not None and later <= earlier
        for earlier, later in zip(budgets, budgets[1:])
    )


def test_termination_record_serializes_provider_owner_id(tmp_path: Path) -> None:
    from core_tools.provider.process_identity import (
        process_identity_from_termination_record,
    )

    provider, entry = _ownerless_mismatch_entry(tmp_path)
    entry.owner_id = "owner-a"
    entry.identity = ProcessIdentity(
        pid=4242, start_time="100", run_id="run-a", owner_id="owner-a"
    )
    record = provider._termination_record_for_tracked_proc(entry)
    assert record["provider_owner_id"] == "owner-a"
    restored = process_identity_from_termination_record(record)
    assert restored is not None
    assert restored.owner_id == "owner-a"
