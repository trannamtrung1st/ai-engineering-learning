"""Slice 5 sixteenth re-review regressions (S5-RR16-002 TDP reconcile)."""

from __future__ import annotations

from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import ProcessIdentity
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions


def test_teardown_succeeds_after_external_child_retry_when_group_is_gone(tmp_path) -> None:
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
    leader = ProcessIdentity(pid=4242, start_time="100", run_id="run-rr16")
    child = ProcessIdentity(pid=5151, start_time="200", run_id="run-rr16")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader, child),
    )

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.GONE,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
                return_value=False,
            ):
                teardown_provider_sessions(
                    provider,
                    run_id="run-rr16",
                    phase=PLANNING,
                    append_event=lambda *_args, **_kwargs: None,
                    emit_console=lambda _event: None,
                    audit_cancel=True,
                )

    assert provider.list_active_sessions() == []
    assert 4242 not in provider._tracked_turn_procs
