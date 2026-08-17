"""Slice 5 rereview 3e3ec52: current-member PGID lineage, idle enrich, spawn FDs."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import ProcessGroupState, posix_spawn_session_leader
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
    current_process_group_lineage,
)
from tests.conftest import tracked_turn_proc


def _idle_config(*, idle: float = 0.08, start_timeout: float = 2.0) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
                "agent_start_timeout_seconds": start_timeout,
            }
        }
    }


def _provider(tmp_path: Path, runner=None, *, idle: float = 0.0) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(idle=idle),
        workspace=tmp_path,
        runner=runner or (lambda argv, cwd: iter(())),
        binary=str(agent),
        skip_probe=True,
    )


def _gone_live_entry(tmp_path: Path, *, run_id: str | None = "run-owned"):
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100", run_id=run_id)
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.member_identities = (leader,)
    entry.pgid = 4242
    entry.proc = None
    entry.group_observed_gone = False
    return provider, entry


def test_gone_identities_keep_tree_when_current_member_matches_run(
    tmp_path: Path,
) -> None:
    provider, entry = _gone_live_entry(tmp_path)
    late = ProcessIdentity(pid=5151, start_time="200", run_id="run-owned")
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
    del late


def test_gone_identities_release_tree_when_current_members_are_foreign(
    tmp_path: Path,
) -> None:
    provider, entry = _gone_live_entry(tmp_path)
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
        return_value=GroupLineageState.FOREIGN,
    ):
        assert provider._tracked_tree_is_live(entry) is False


def test_gone_identities_stay_unresolved_without_current_member_proof(
    tmp_path: Path,
) -> None:
    provider, entry = _gone_live_entry(tmp_path, run_id="run-rr17")
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
        return_value=GroupLineageState.UNRESOLVED,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_lineage_foreign_when_live_members_have_other_run_id() -> None:
    foreign = ProcessIdentity(pid=9999, start_time="9", run_id="other-run")
    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=[foreign],
    ):
        assert (
            current_process_group_lineage(4242, expected_run_id="run-owned")
            is GroupLineageState.FOREIGN
        )


def test_lineage_owned_when_live_member_shares_run_id() -> None:
    owned = ProcessIdentity(pid=5151, start_time="200", run_id="run-owned")
    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=[owned],
    ):
        assert (
            current_process_group_lineage(4242, expected_run_id="run-owned")
            is GroupLineageState.OWNED
        )


def test_lineage_unresolved_when_group_members_cannot_be_listed() -> None:
    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=None,
    ):
        assert (
            current_process_group_lineage(4242, expected_run_id="run-owned")
            is GroupLineageState.UNRESOLVED
        )


def test_lineage_gone_when_process_group_state_is_gone() -> None:
    with patch(
        "core_tools.provider.process_identity.process_group_state",
        return_value=ProcessGroupState.GONE,
    ):
        assert (
            current_process_group_lineage(4242, expected_run_id="run-owned")
            is GroupLineageState.GONE
        )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX spawn")
def test_posix_spawn_overlapping_stdout_fd_restores_original_inheritable() -> None:
    result_r, result_w = os.pipe()
    os.set_inheritable(result_w, False)

    def fake_spawn(path, argv, env, **kwargs):
        del path, argv, env, kwargs
        assert os.get_inheritable(result_w) is True
        return 1

    try:
        with patch("core_tools.provider.process_cleanup.os.posix_spawn", fake_spawn):
            posix_spawn_session_leader(
                [sys.executable, "-c", "pass"],
                stdout_fd=result_w,
                inherit_fds=(result_w,),
            )
        assert os.get_inheritable(result_w) is False
    finally:
        os.close(result_r)
        os.close(result_w)


def test_second_stream_line_arrives_before_slow_identity(tmp_path: Path) -> None:
    from core_tools.provider.cursor import _SubprocessStdoutIterator

    init = json.dumps({"type": "system", "subtype": "init", "session_id": "chat-fast"})
    text = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "n"}]}}
    )
    script = (
        "import sys\n"
        f"print({init!r}, flush=True)\n"
        f"print({text!r}, flush=True)\n"
        "import time\n"
        "time.sleep(0.3)\n"
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    def slow_identity(pid, run_id=None, command=None, timeout=None):
        del pid, run_id, command
        time.sleep(0.2)
        if timeout is not None and timeout == 0:
            return None
        return ProcessIdentity(pid=424242, start_time="synthetic-test")

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(idle=0.0, start_timeout=2.0),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with patch(
        "core_tools.provider.cursor.read_process_identity",
        side_effect=slow_identity,
    ), patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        return_value=None,
    ):
        started = time.monotonic()
        got_assistant = False
        for event in provider.stream_events(session_id):
            if event.get("type") == "assistant":
                got_assistant = True
                elapsed = time.monotonic() - started
                break
        else:
            elapsed = time.monotonic() - started
        provider.terminate_session(session_id)
    assert got_assistant
    assert elapsed < 0.2
