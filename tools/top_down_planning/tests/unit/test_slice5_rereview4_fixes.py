"""Slice 5 fourth re-review regression tests (S5-RR4-001 through S5-RR4-005)."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.agent_process_cleanup import OrphanCleanupResult
from top_down_planning.orchestrator.errors import ProviderTeardownError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.run_signals import (
    defer_run_interrupt_signals,
    ignore_repeated_run_interrupt_signals,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr4",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def _agent_command() -> str:
    return "agent --output-format stream-json --trust"


def test_teardown_defers_session_ended_until_pid_death_confirmed() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[tuple[str, dict]] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append((event_type, dict(fields)))

    with patch(
        "top_down_planning.orchestrator.provider_teardown.terminate_pid_tree",
        return_value=False,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
            return_value=True,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.pid_matches_run_agent",
                return_value=True,
            ):
                with patch.object(
                    provider,
                    "terminate_all_sessions",
                    return_value=[
                        {
                            "pid": 111,
                            "role": "planner",
                            "session_id": session_id,
                            "reason": "termination_failed",
                        }
                    ],
                ):
                    with pytest.raises(ProviderTeardownError):
                        teardown_provider_sessions(
                            provider,
                            run_id="run-test",
                            phase=PLANNING,
                            append_event=append_event,
                            emit_console=lambda _event: None,
                            audit_cancel=True,
                        )

    ended_types = [event_type for event_type, _fields in events if event_type.endswith("_session_ended")]
    assert ended_types == []
    assert any(event_type == "agent_orphan_cleanup_failed" for event_type, _fields in events)


def test_teardown_emits_session_ended_only_after_retry_success() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[tuple[str, dict]] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append((event_type, dict(fields)))

    alive = {"111": True}

    def fake_is_alive(pid: int) -> bool:
        return alive.get(str(pid), False)

    def fake_terminate(pid: int) -> bool:
        alive[str(pid)] = False
        return True

    def mock_terminate_all_sessions() -> list[dict[str, object]]:
        provider._sessions.clear()
        return [
            {
                "pid": 111,
                "role": "planner",
                "session_id": session_id,
                "reason": "termination_failed",
            }
        ]

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        side_effect=fake_is_alive,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_pid_tree",
            side_effect=fake_terminate,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.pid_matches_run_agent",
                return_value=True,
            ):
                with patch.object(
                    provider,
                    "terminate_all_sessions",
                    side_effect=mock_terminate_all_sessions,
                ):
                    terminated = teardown_provider_sessions(
                        provider,
                        run_id="run-test",
                        phase=PLANNING,
                        append_event=append_event,
                        emit_console=lambda _event: None,
                        audit_cancel=True,
                    )

    assert terminated == [111]
    ended = [event_type for event_type, _fields in events if event_type == "planner_session_ended"]
    assert ended == ["planner_session_ended"]
    agent_failed = [event_type for event_type, _fields in events if event_type == "agent_termination_failed"]
    assert agent_failed == ["agent_termination_failed"]
    ended_index = next(i for i, (event_type, _fields) in enumerate(events) if event_type == "planner_session_ended")
    failed_index = next(i for i, (event_type, _fields) in enumerate(events) if event_type == "agent_termination_failed")
    assert ended_index > failed_index


def test_defer_run_interrupt_signals_replays_sigint_after_teardown() -> None:
    previous = signal.getsignal(signal.SIGINT)
    completed: list[str] = []

    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        with defer_run_interrupt_signals():
            signal.raise_signal(signal.SIGINT)
            completed.append("teardown")
        completed.append("after")
    except KeyboardInterrupt:
        completed.append("cancelled")
    finally:
        signal.signal(signal.SIGINT, previous)

    assert completed == ["teardown", "cancelled"]


def test_defer_run_interrupt_signals_replays_sigterm_after_teardown() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    completed: list[str] = []

    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        with defer_run_interrupt_signals():
            signal.raise_signal(signal.SIGTERM)
            completed.append("teardown")
    except KeyboardInterrupt:
        completed.append("cancelled")
    finally:
        signal.signal(signal.SIGTERM, previous)

    assert completed == ["teardown", "cancelled"]


def test_ignore_repeated_run_interrupt_signals_drops_extra_signals() -> None:
    previous = signal.getsignal(signal.SIGINT)
    completed: list[str] = []

    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        with ignore_repeated_run_interrupt_signals():
            signal.raise_signal(signal.SIGINT)
            signal.raise_signal(signal.SIGINT)
            completed.append("persisted")
    finally:
        signal.signal(signal.SIGINT, previous)

    assert completed == ["persisted"]


def test_teardown_preserves_verified_pids_when_audit_append_raises() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    provider.start_primary_session("planner", {"goal": "x"})
    calls = {"count": 0}

    def append_event(event_type: str, **fields: object) -> None:
        calls["count"] += 1
        if event_type == "agent_terminated":
            raise RuntimeError("audit append failed")

    with patch.object(
        provider,
        "terminate_all_sessions",
        return_value=[
            {
                "pid": 111,
                "role": "planner",
                "session_id": "stub-session",
                "reason": "terminated",
            }
        ],
    ):
        with pytest.raises(ProviderTeardownError) as exc_info:
            teardown_provider_sessions(
                provider,
                run_id="run-test",
                phase=PLANNING,
                append_event=append_event,
                emit_console=lambda _event: None,
                audit_cancel=True,
            )

    assert exc_info.value.terminated_pids == (111,)


def test_teardown_preserves_verified_pids_when_console_emit_raises() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    provider.start_primary_session("planner", {"goal": "x"})

    def append_event(_event_type: str, **_fields: object) -> None:
        return None

    def emit_console(_event: object) -> None:
        raise RuntimeError("console emit failed")

    with patch.object(
        provider,
        "terminate_all_sessions",
        return_value=[
            {
                "pid": 222,
                "role": "planner",
                "session_id": "stub-session",
                "reason": "terminated",
            }
        ],
    ):
        with pytest.raises(ProviderTeardownError) as exc_info:
            teardown_provider_sessions(
                provider,
                run_id="run-test",
                phase=PLANNING,
                append_event=append_event,
                emit_console=emit_console,
                audit_cancel=False,
            )

    assert exc_info.value.terminated_pids == (222,)


def test_engine_cancel_includes_partial_teardown_pids_when_audit_raises(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020101-020101"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    provider.script_turn(done_events(text="ok"))

    def interrupt_and_raise(self: PlanningPhaseOrchestrator) -> None:
        provider.start_primary_session("planner", {"goal": "x"})
        raise KeyboardInterrupt

    with patch.object(PlanningPhaseOrchestrator, "run", interrupt_and_raise):
        with patch(
            "top_down_planning.orchestrator.engine.teardown_provider_sessions",
            side_effect=ProviderTeardownError(
                "audit append failed",
                terminated_pids=(111,),
                surviving_pids=(),
            ),
        ):
            with patch(
                "top_down_planning.orchestrator.engine.verify_run_agent_survivors",
            ) as verify_mock:
                from top_down_planning.orchestrator.provider_teardown import (
                    TeardownVerificationResult,
                )

                verify_mock.return_value = TeardownVerificationResult(
                    terminated_pids=(111, 5555),
                    surviving_pids=(),
                )
                result = RunEngine(
                    store,
                    create_provider=lambda _config, _workspace: provider,
                ).continue_run(run_id, single_step=True)

    assert result.cancelled is True
    stored = store.load_run(run_id)
    assert stored["stop"]["details"]["terminated_pids"] == [111, 5555]


def test_doctor_fix_refuses_destructive_repair_for_live_owned_running_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020201-020201"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    store.save_run(run_id, run, expected_revision)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
        ) as kill_mock:
            handle_doctor_command(
                type(
                    "Args",
                    (),
                    {
                        "run": run_id,
                        "fix": True,
                        "stream_json": False,
                        "runs_dir": str(store.root),
                        "config": None,
                    },
                )()
            )

    kill_mock.assert_not_called()
    output = capsys.readouterr().out
    assert "refusing destructive repair" in output.lower()


def test_doctor_fix_allows_repair_for_stale_running_run(tmp_path: Path) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020301-020301"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    store.save_run(run_id, run, expected_revision)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=()),
        ) as kill_mock:
            with patch(
                "top_down_planning.cli.doctor.reconcile_stale_running_run_under_ownership",
                return_value=True,
            ) as reconcile_mock:
                handle_doctor_command(
                    type(
                        "Args",
                        (),
                        {
                            "run": run_id,
                            "fix": True,
                            "stream_json": False,
                            "runs_dir": str(store.root),
                            "config": None,
                        },
                    )()
                )

    kill_mock.assert_called_once()
    reconcile_mock.assert_called_once()
