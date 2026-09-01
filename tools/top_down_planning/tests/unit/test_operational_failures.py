"""Tests for operational failure handling (proposal §15)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.observability import ConsoleEvent
from core_tools.persistence import PersistenceError
from core_tools.provider.stub import StubProvider
from top_down_planning.cli.user import handle_resume_command
from top_down_planning.cli.user import handle_status_command
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.observability import ObservabilityContext
from top_down_planning.orchestrator import mark_run_failed, sanitize_operational_error
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.errors import OrchestratorInvariantError, ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _set_planner_session_for_resume(
    store: FileRunStore,
    run_id: str,
    *,
    session_id: str = "stub-planner-session",
) -> None:
    from top_down_planning.persistence.session_bindings import update_primary_binding

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": "planning",
        "message": "cancelled by user",
        "details": {},
    }
    run["sessions"] = update_primary_binding(
        dict(run.get("sessions") or {}),
        role="planner",
        provider_session_id=session_id,
    )
    store.save_run(run_id, run, expected_revision)


def _create_run(
    store: FileRunStore,
    run_id: str = "run-20260101T001701-001701",
    *,
    phase: str = WHOLE_PLAN_REVIEW,
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    config = minimal_resolved_config(
        run={"output_goal": "Deliver the feature.", "input_refs": []},
        planning={"max_depth": 4, "max_expansion_per_item": 7},
    )
    config["project"]["workspace"] = str(store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=phase,
    )


def test_mark_run_failed_persists_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    mark_run_failed(store, "run-20260101T001701-001701", message="provider crashed")

    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "orchestrator_invariant_failure"
    events = store.load_events("run-20260101T001701-001701")
    assert any(event.get("type") == "run_failed" for event in events)


def test_sanitize_operational_error_redacts_paths() -> None:
    message = sanitize_operational_error(
        RuntimeError("failed to write /tmp/secret/run.json")
    )
    assert "/tmp/secret/run.json" not in message
    assert "<path>" in message


def test_cli_status_reports_persisted_run_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T001801-001801")

    with patch("top_down_planning.cli.user.emit_payload") as emit_payload:
        emit_payload.side_effect = lambda payload, **kwargs: (_ for _ in ()).throw(SystemExit(0))
        with pytest.raises(SystemExit) as exit_info:
            handle_status_command(
                Namespace(run="run-20260101T001801-001801", runs_dir=str(store.root), stream_json=True)
            )
        assert exit_info.value.code == 0
        payload = emit_payload.call_args.args[0]

    assert payload["ok"] is True
    assert payload["run"]["id"] == "run-20260101T001801-001801"
    assert payload["run"]["phase"] == WHOLE_PLAN_REVIEW
    assert payload["run"]["status"] == "running"
    assert "config_contract" in payload["run"]["digests"]
    assert "config_execution" in payload["run"]["digests"]


def test_engine_provider_run_error_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=ProviderRunError("provider crashed"),
    ):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "orchestrator_state_conflict"
    events = store.load_events("run-20260101T001701-001701")
    assert any(event.get("type") == "run_paused" for event in events)


def test_engine_provider_turn_error_pauses_run(tmp_path: Path) -> None:
    from core_tools.provider.errors import ProviderTurnError

    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=ProviderTurnError(
            "provider turn already in progress for session cursor-abc",
            session_id="cursor-abc",
        ),
    ):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "provider_turn_failed"
    assert run["stop"]["category"] == "operational"


def test_engine_orchestrator_invariant_error_fails_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=OrchestratorInvariantError("advisory policy invariant"),
    ):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "orchestrator_invariant_failure"


def test_engine_operational_exception_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=RuntimeError("orchestrator exploded"),
    ):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    assert result.reason == "orchestrator exploded"
    assert store.load_run("run-20260101T001701-001701")["status"] == "failed"


def test_engine_store_exception_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=PersistenceError("disk full"),
    ):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    assert store.load_run("run-20260101T001701-001701")["status"] == "failed"


def test_engine_keyboard_interrupt_terminates_provider_sessions(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    provider = StubProvider()
    terminated: list[bool] = []
    original_terminate = provider.terminate_all_sessions

    def spy_terminate() -> list[dict[str, object]]:
        terminated.append(True)
        return original_terminate()

    provider.terminate_all_sessions = spy_terminate  # type: ignore[method-assign]

    collector: list[ConsoleEvent] = []

    class _CollectSink:
        def emit(self, event: ConsoleEvent) -> None:
            collector.append(event)

    observability = ObservabilityContext(sink=_CollectSink(), run_id="run-20260101T001701-001701")
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
        observability=observability,
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=KeyboardInterrupt,
    ):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.cancelled is True
    assert result.ok is False
    assert result.reason == "cancelled by user"
    assert terminated == [True]
    cancel_events = [event for event in collector if event.category == "session:cancel"]
    assert len(cancel_events) == 1
    assert cancel_events[0].fields["phase"] == PLANNING
    assert "run-20260101T001701-001701" in cancel_events[0].message
    assert store.load_run("run-20260101T001701-001701")["status"] == "paused"
    assert (
        store.load_run("run-20260101T001701-001701")["stop"]["code"] == "user_cancelled"
    )


def test_engine_keyboard_interrupt_persists_cancel_when_teardown_raises(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    provider = StubProvider()

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=KeyboardInterrupt,
    ):
        with patch(
            "top_down_planning.orchestrator.engine.teardown_provider_sessions",
            side_effect=RuntimeError("teardown exploded"),
        ):
            result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.cancelled is True
    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"


def test_engine_emits_session_end_before_terminate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    collector: list[ConsoleEvent] = []

    class _CollectSink:
        def emit(self, event: ConsoleEvent) -> None:
            collector.append(event)

    observability = ObservabilityContext(sink=_CollectSink(), run_id="run-20260101T001701-001701")
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
        observability=observability,
    )

    def start_session_and_interrupt(self: PlanningPhaseOrchestrator) -> None:
        self._provider.start_primary_session("planner", {"goal": "x"})
        raise KeyboardInterrupt

    with patch.object(PlanningPhaseOrchestrator, "run", start_session_and_interrupt):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.cancelled is True
    end_events = [event for event in collector if event.category == "session:end"]
    assert len(end_events) == 1
    assert end_events[0].fields["phase"] == PLANNING
    assert end_events[0].fields["role"] == "planner"
    assert end_events[0].fields["model"] == "auto"
    assert end_events[0].session_id is not None
    cancel_index = next(
        index for index, event in enumerate(collector) if event.category == "session:cancel"
    )
    end_index = next(
        index for index, event in enumerate(collector) if event.category == "session:end"
    )
    assert cancel_index < end_index


def test_resume_keyboard_interrupt_exits_without_marking_failed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    _set_planner_session_for_resume(store, "run-20260101T001701-001701")

    with patch("top_down_planning.cli.user.emit_message"):
        with patch("top_down_planning.cli.user._build_run_engine") as build_engine:
            build_engine.return_value.continue_run.side_effect = KeyboardInterrupt
            with pytest.raises(SystemExit) as exit_info:
                handle_resume_command(
                    Namespace(
                        run="run-20260101T001701-001701",
                        runs_dir=str(store.root),
                        stream_json=False,
                        check=False,
                        set=[],
                        config=None,
                        command="resume",
                    )
                )
            assert exit_info.value.code == 130

    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "running"
    assert run.get("stop") is None


def test_resume_keyboard_interrupt_persists_cancel_during_preflight(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    _set_planner_session_for_resume(store, "run-20260101T001701-001701")
    run = store.load_run("run-20260101T001701-001701")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    run["stop"] = None
    store.save_run("run-20260101T001701-001701", run, expected_revision)

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch(
        "top_down_planning.orchestrator.engine.execute_session_policy",
        side_effect=KeyboardInterrupt,
    ):
        result = engine.continue_run("run-20260101T001701-001701")

    assert result.cancelled is True
    assert result.ok is False
    paused = store.load_run("run-20260101T001701-001701")
    assert paused["status"] == "paused"
    assert paused["stop"]["code"] == "user_cancelled"


def test_resume_keyboard_interrupt_stream_json_payload(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    _set_planner_session_for_resume(store, "run-20260101T001701-001701")

    with patch.object(
        RunEngine,
        "continue_run",
        side_effect=KeyboardInterrupt,
    ):
        with patch("top_down_planning.cli.user.emit_payload") as emit_payload:
            with pytest.raises(SystemExit) as exit_info:
                handle_resume_command(
                    Namespace(
                        run="run-20260101T001701-001701",
                        runs_dir=str(store.root),
                        stream_json=True,
                        check=False,
                        set=[],
                        config=None,
                        command="resume",
                    )
                )
            assert exit_info.value.code == 130
            payload = emit_payload.call_args.args[0]

    assert payload["cancelled"] is False
    assert payload["command_interrupted"] is True
    assert payload["reason"] == "command interrupted by user"
    assert payload["run_id"] == "run-20260101T001701-001701"


def test_provider_run_error_resume_exits_nonzero(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    _set_planner_session_for_resume(store, "run-20260101T001701-001701")

    with patch("top_down_planning.cli.user.emit_message"):
        with patch("top_down_planning.cli.user._build_run_engine") as build_engine:
            build_engine.return_value.continue_run.side_effect = ProviderRunError(
                "provider crashed"
            )
            with pytest.raises(ProviderRunError, match="provider crashed"):
                handle_resume_command(
                    Namespace(
                        run="run-20260101T001701-001701",
                        runs_dir=str(store.root),
                        stream_json=False,
                        check=False,
                        set=[],
                        config=None,
                        command="resume",
                    )
                )

    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] != "failed"


def test_operational_failed_run_cannot_be_resumed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    mark_run_failed(store, "run-20260101T001701-001701", message="provider crashed")

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )
    result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    assert result.reason == "failed runs cannot be resumed"
    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "failed"
    assert run["stop"]["category"] == "invariant"


def test_operational_paused_run_cannot_be_resumed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    run = store.load_run("run-20260101T001701-001701")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PLANNING,
        "message": "limit reached",
        "details": {
            "limit": "limits.planning.max_agent_turns",
            "consumed": 1,
            "configured": 1,
        },
    }
    store.save_run("run-20260101T001701-001701", run, expected_revision)

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )
    result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.ok is False
    assert "paused" in (result.reason or "")
    assert store.load_run("run-20260101T001701-001701")["status"] == "paused"


def test_resume_cli_rejects_failed_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    mark_run_failed(store, "run-20260101T001701-001701", message="provider crashed")

    with patch("top_down_planning.cli.user.emit_error_message") as emit_error:
        handle_resume_command(
            Namespace(run="run-20260101T001701-001701", runs_dir=str(store.root), stream_json=False)
        )
        emit_error.assert_called_once()
        assert emit_error.call_args.kwargs["code"] == "failed_run_not_resumable"
