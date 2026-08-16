"""Slice 5 rereview 4ef1c72: portable owner lineage, proxy CLEAN, signal isolation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
    current_process_group_lineage,
    read_process_owner_id,
)
from core_tools.provider.session_janitor import DrainResult, _signal_group
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


def test_same_run_different_provider_owner_is_foreign() -> None:
    foreign = ProcessIdentity(
        pid=9999,
        start_time="9",
        run_id="run-a",
        owner_id="owner-b",
    )
    with patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=[foreign],
    ):
        assert (
            current_process_group_lineage(
                4242,
                expected_run_id="run-a",
                expected_owner_id="owner-a",
            )
            is GroupLineageState.FOREIGN
        )


def test_same_provider_owner_is_owned() -> None:
    owned = ProcessIdentity(
        pid=5151,
        start_time="200",
        run_id="run-a",
        owner_id="owner-a",
    )
    with patch(
        "core_tools.provider.process_identity._current_group_identities",
        return_value=[owned],
    ):
        assert (
            current_process_group_lineage(
                4242,
                expected_run_id="run-a",
                expected_owner_id="owner-a",
            )
            is GroupLineageState.OWNED
        )


def test_darwin_ps_line_exposes_provider_owner_id() -> None:
    ps = (
        "  PID TTY           TIME CMD\n"
        " 5151 ??         0:00.01 python TDP_RUN_ID=run-a "
        "TDP_PROVIDER_OWNER_ID=owner-a agent\n"
    )

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = ps

        return Result()

    with patch("sys.platform", "darwin"), patch(
        "core_tools.provider.process_identity.subprocess.run",
        fake_run,
    ), patch("os.path.isdir", return_value=False):
        assert read_process_owner_id(5151) == "owner-a"


def test_gone_identities_release_when_current_owner_differs(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(
        pid=4242, start_time="100", run_id="run-a", owner_id="owner-a"
    )
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    entry = provider._tracked_turn_procs[4242]
    entry.identity = leader
    entry.owner_id = "owner-a"
    entry.member_identities = (leader,)
    entry.pgid = 4242
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
        return_value=GroupLineageState.FOREIGN,
    ):
        assert provider._tracked_tree_is_live(entry) is False


def test_signal_group_does_not_broadcast_into_parent_process_group() -> None:
    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    with patch("core_tools.provider.session_janitor.os.getpgrp", return_value=100), patch(
        "core_tools.provider.session_janitor.os.getppid", return_value=1
    ), patch(
        "core_tools.provider.session_janitor.os.getpgid", return_value=100
    ), patch(
        "core_tools.provider.session_janitor.os.killpg", fake_killpg
    ):
        _signal_group(9)
    assert calls == []


def test_clean_requires_proxy_threads_to_be_terminal() -> None:
    from core_tools.provider.session_janitor import drain_result_if_proxies_live

    assert (
        drain_result_if_proxies_live(DrainResult.CLEAN, proxies_done=False)
        is DrainResult.SURVIVORS
    )
    assert (
        drain_result_if_proxies_live(DrainResult.CLEAN, proxies_done=True)
        is DrainResult.CLEAN
    )
