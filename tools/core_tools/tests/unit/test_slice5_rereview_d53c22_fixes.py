"""Slice 5 rereview d53c22: ownerless GONE vs mismatch, no secondary CLEAN bypass."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
    _terminate_bound_process,
)
from core_tools.provider.session_janitor import DrainResult, JanitorStatusOwner
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


def _ownerless_entry(tmp_path: Path):
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


def test_ownerless_gone_identities_keep_live_pgid_as_late_descendant(
    tmp_path: Path,
) -> None:
    provider, entry = _ownerless_entry(tmp_path)
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


def test_ownerless_mismatched_identities_do_not_pin_reused_pgid(
    tmp_path: Path,
) -> None:
    provider, entry = _ownerless_entry(tmp_path)
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


def test_ownerless_unverifiable_identities_keep_live_pgid_as_late_descendant(
    tmp_path: Path,
) -> None:
    provider, entry = _ownerless_entry(tmp_path)
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.inspect_process_identity",
        return_value=IdentityInspectState.UNVERIFIABLE,
    ), patch(
        "core_tools.provider.cursor.current_process_group_lineage",
        return_value=GroupLineageState.UNRESOLVED,
    ):
        assert provider._tracked_tree_is_live(entry) is True


def test_secondary_clean_refuses_pending_janitor_status() -> None:
    from core_tools.provider.session_janitor import complete_bound_secondary_clean

    class Proc:
        pid = 4242

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    proc = Proc()
    owner = JanitorStatusOwner(-1)
    owner._fd = None
    proc._core_tools_janitor_status_owner = owner
    assert complete_bound_secondary_clean(proc) is False
    assert owner.reap_allowed is False


def test_reap_verifier_does_not_killpg_when_pid_is_not_session_leader() -> None:
    from core_tools.provider.session_janitor import _reap_verifier

    class Proc:
        pid = 4242

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    def fake_getpgid(pid: int) -> int:
        if pid == 4242:
            return 99
        return 1

    with patch(
        "core_tools.provider.session_janitor.os.killpg"
    ) as killpg, patch(
        "core_tools.provider.session_janitor.os.getpgid",
        side_effect=fake_getpgid,
    ):
        _reap_verifier(Proc(), timeout=0.0)
    killpg.assert_not_called()


def test_secondary_clean_does_not_upgrade_unverifiable_fallback() -> None:
    class Proc:
        pid = 4242
        args = ["janitor"]

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    proc = Proc()
    owner = JanitorStatusOwner(-1)
    owner._fd = None
    proc._core_tools_janitor_status_owner = owner
    with patch(
        "core_tools.provider.process_identity._terminate_via_bound_popen",
        return_value={
            "agent_code": -1,
            "drain": DrainResult.UNVERIFIABLE.value,
            "stop_requested": True,
        },
    ), patch(
        "core_tools.provider.process_identity.drain_owned_process_group",
        return_value=True,
    ):
        result = _terminate_bound_process(None, proc, pgid=4242)
    assert result is not TerminateIdentityResult.TERMINATED
    assert owner.reap_allowed is False
