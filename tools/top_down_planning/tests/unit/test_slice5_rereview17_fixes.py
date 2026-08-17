"""Slice 5 seventeenth re-review TDP regressions (S5-RR17-003)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import (
    GroupLineageState,
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
)
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import (
    ProviderTeardownError,
    teardown_provider_sessions,
)


def test_teardown_retains_session_when_group_still_live_after_known_identities_die(
    tmp_path,
) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-rr17")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader,),
    )

    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.ALREADY_GONE,
    ):
        with patch(
            "core_tools.provider.cursor.process_identity_is_live",
            return_value=False,
        ):
            with patch(
                "core_tools.provider.cursor.process_group_state",
                return_value=ProcessGroupState.LIVE,
            ):
                with patch(
                    "core_tools.provider.cursor.inspect_process_identity",
                    return_value=IdentityInspectState.GONE,
                ):
                    with patch(
                        "core_tools.provider.cursor.current_process_group_lineage",
                        return_value=GroupLineageState.OWNED,
                    ):
                        with patch(
                            "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
                            return_value=False,
                        ):
                            with pytest.raises(ProviderTeardownError, match="active sessions"):
                                teardown_provider_sessions(
                                    provider,
                                    run_id="run-rr17",
                                    phase=PLANNING,
                                    append_event=lambda *_args, **_kwargs: None,
                                    emit_console=lambda _event: None,
                                    audit_cancel=True,
                                )

    assert session_id in {s["session_id"] for s in provider.list_active_sessions()}
    assert 4242 in provider._tracked_turn_procs
