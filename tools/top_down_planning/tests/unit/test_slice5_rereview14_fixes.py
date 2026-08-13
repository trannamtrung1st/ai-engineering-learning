"""Slice 5 fourteenth re-review regressions (S5-RR14-002 and S5-RR14-003)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.process_identity import ProcessIdentity
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import (
    _emit_agent_termination_records,
    _session_surviving_pids,
    teardown_provider_sessions,
)


def test_session_surviving_pids_exclude_reused_member_pid() -> None:
    session = {"session_id": "cursor-session-1", "role": "planner"}
    records = [
        {
            "pid": 4242,
            "role": "planner",
            "session_id": "cursor-session-1",
            "start_time": "100",
            "process_identity": "4242:100",
            "member_pids": [4242, 5151],
            "member_identities": ["4242:100", "5151:200"],
            "tree_status": "unresolved",
            "reason": "termination_failed",
        }
    ]

    class _Provider:
        def canonical_session_id(self, session_id: str) -> str:
            return session_id

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.process_identity_is_live",
            return_value=False,
        ):
            survivors = _session_surviving_pids(
                session,
                provider=_Provider(),  # type: ignore[arg-type]
                termination_records=records,
            )

    assert survivors == []


def test_legacy_pid_only_record_is_not_treated_as_live_occupant() -> None:
    session = {"session_id": "cursor-session-1", "role": "planner"}
    records = [
        {
            "pid": 4242,
            "session_id": "cursor-session-1",
            "reason": "termination_failed",
        }
    ]

    class _Provider:
        def canonical_session_id(self, session_id: str) -> str:
            return session_id

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        survivors = _session_surviving_pids(
            session,
            provider=_Provider(),  # type: ignore[arg-type]
            termination_records=records,
        )

    assert survivors == []


def test_agent_termination_failed_event_preserves_tree_metadata() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append((event_type, fields))

    _emit_agent_termination_records(
        append_event,
        phase=PLANNING,
        records=[
            {
                "pid": 4242,
                "role": "planner",
                "session_id": "cursor-session-1",
                "start_time": "100",
                "process_identity": "4242:100",
                "run_id": "run-rr14",
                "pgid": 4242,
                "member_identities": ["4242:100", "5151:200"],
                "tree_status": "unresolved",
                "reason": "termination_failed",
            }
        ],
        audit_cancel=True,
    )

    assert events == [
        (
            "agent_termination_failed",
            {
                "pid": 4242,
                "role": "planner",
                "session_id": "cursor-session-1",
                "phase": PLANNING,
                "reason": "termination_failed",
                "start_time": "100",
                "process_identity": "4242:100",
                "run_id": "run-rr14",
                "pgid": 4242,
                "member_identities": ["4242:100", "5151:200"],
                "tree_status": "unresolved",
            },
        )
    ]


def test_teardown_audit_excludes_reused_member_pid(tmp_path: Path) -> None:
    from core_tools.provider import StubProvider

    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[dict[str, object]] = []

    def terminate_all_sessions() -> list[dict[str, object]]:
        return [
            {
                "pid": 4242,
                "role": "planner",
                "session_id": session_id,
                "start_time": "100",
                "process_identity": "4242:100",
                "run_id": "run-rr14",
                "pgid": 4242,
                "member_pids": [4242, 5151],
                "member_identities": ["4242:100", "5151:200"],
                "tree_status": "unresolved",
                "reason": "termination_failed",
            }
        ]

    with patch.object(provider, "terminate_all_sessions", side_effect=terminate_all_sessions):
        with patch.object(provider, "list_active_sessions", return_value=[]):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
                return_value=True,
            ):
                with patch(
                    "top_down_planning.orchestrator.provider_teardown.process_identity_is_live",
                    return_value=False,
                ):
                    with patch(
                        "top_down_planning.orchestrator.provider_teardown.read_process_identity",
                        return_value=ProcessIdentity(
                            pid=5151, start_time="999", run_id="run-rr14"
                        ),
                    ):
                        teardown_provider_sessions(
                            provider,
                            run_id="run-rr14",
                            phase=PLANNING,
                            append_event=lambda event_type, **fields: events.append(
                                {"type": event_type, **fields}
                            ),
                            emit_console=lambda _event: None,
                            audit_cancel=True,
                        )

    failed = [event for event in events if event["type"] == "agent_termination_failed"]
    assert failed
    assert failed[0]["tree_status"] == "unresolved"
    assert failed[0]["process_identity"] == "4242:100"
    assert failed[0]["pgid"] == 4242
    assert failed[0]["member_identities"] == ["4242:100", "5151:200"]
    assert not any(
        event["type"] == "provider_session_teardown_failed" for event in events
    )
    assert not any(event.get("pid") == 5151 for event in events)
