"""Slice 5 rereview 32de281: mismatch lineage, escalation CLEAN, bounded env read."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
)
from core_tools.provider.session_janitor import DrainResult, drain_result_if_proxies_live
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


def _mismatch_entry(tmp_path: Path):
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
    return provider, entry


def test_leader_mismatch_keeps_tree_when_current_owner_matches(tmp_path: Path) -> None:
    provider, entry = _mismatch_entry(tmp_path)
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


def test_leader_mismatch_stays_unresolved_without_current_owner_proof(
    tmp_path: Path,
) -> None:
    provider, entry = _mismatch_entry(tmp_path)
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
        assert provider._tracked_tree_is_live(entry) is True


def test_leader_mismatch_releases_when_current_owners_are_foreign(tmp_path: Path) -> None:
    provider, entry = _mismatch_entry(tmp_path)
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
        return_value=GroupLineageState.FOREIGN,
    ):
        assert provider._tracked_tree_is_live(entry) is False


def test_mixed_mismatch_and_gone_keeps_tree_when_current_owner_matches(
    tmp_path: Path,
) -> None:
    provider, entry = _mismatch_entry(tmp_path)

    def fake_inspect(identity, *, timeout=None):
        del timeout
        if identity.pid == 4242:
            return IdentityInspectState.IDENTITY_MISMATCH
        return IdentityInspectState.GONE

    child = ProcessIdentity(pid=5151, start_time="200", run_id="run-a", owner_id="owner-a")
    entry.member_identities = (entry.identity, child)
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        side_effect=fake_inspect,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.OWNED,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_escalation_clean_is_downgraded_while_proxies_live() -> None:
    assert (
        drain_result_if_proxies_live(DrainResult.CLEAN, proxies_done=False)
        is DrainResult.SURVIVORS
    )


def test_ps_env_read_uses_timeout() -> None:
    seen: dict[str, float | None] = {}

    def fake_run(*_args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")

        class Result:
            returncode = 0
            stdout = "5151 python TDP_PROVIDER_OWNER_ID=owner-a\n"

        return Result()

    with patch("os.path.isdir", return_value=False), patch(
        "core_tools.provider.process_identity.subprocess.run",
        fake_run,
    ):
        from core_tools.provider.process_identity import read_process_owner_id

        assert read_process_owner_id(5151, timeout=0.05) == "owner-a"
    assert seen["timeout"] is not None
    assert seen["timeout"] <= 0.05
