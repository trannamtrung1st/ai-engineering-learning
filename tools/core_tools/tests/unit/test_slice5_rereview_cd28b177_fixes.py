"""Slice 5 rereview cd28b177: reap ZOMBIE_ONLY after owned-session wait."""

from __future__ import annotations

from unittest.mock import patch

from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
    _killpg_owned_session,
)


def test_owned_session_zombie_after_wait_is_reaped_and_terminated() -> None:
    leader = ProcessIdentity(
        pid=4242, start_time="leader", run_id="run-a", owner_id="owner-a"
    )
    reaps: list[int] = []

    def fake_reap(identity: ProcessIdentity) -> None:
        reaps.append(identity.pid)

    def fake_group_state(pgid: int, *, timeout: float | None = None):
        del pgid, timeout
        if len(reaps) >= 2:
            return ProcessGroupState.GONE
        return ProcessGroupState.ZOMBIE_ONLY

    with patch(
        "core_tools.provider.process_identity.is_owned_session_leader",
        side_effect=lambda identity, pgid=None, timeout=None: len(reaps) == 0,
    ), patch(
        "core_tools.provider.process_identity.os.killpg",
        return_value=None,
    ), patch(
        "core_tools.provider.process_identity._reap_identity",
        side_effect=fake_reap,
    ), patch(
        "core_tools.provider.process_identity.wait_process_group_gone",
        return_value=ProcessGroupState.ZOMBIE_ONLY,
    ), patch(
        "core_tools.provider.process_identity.process_group_state",
        side_effect=fake_group_state,
    ):
        result = _killpg_owned_session(leader, timeout=1.0)

    assert result is TerminateIdentityResult.TERMINATED
    assert reaps.count(leader.pid) >= 2
