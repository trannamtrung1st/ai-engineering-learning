"""Tests for agent subprocess orphan detection and cancel cleanup."""

from __future__ import annotations

import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_identity import ProcessIdentity
from core_tools.provider.stub import StubProvider
from top_down_planning.cli.doctor import handle_doctor_command
from top_down_planning.observability import ObservabilityContext
from top_down_planning.orchestrator.agent_process_cleanup import (
    kill_orphan_agents,
    scan_orphan_agent_pids,
    workspace_has_orphan_agents,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config, patch_identity_safe_orphan_scan
from tests.unit.test_operational_failures import _create_run


def test_scan_orphan_agent_pids_uses_stop_details_and_env(tmp_path: Path) -> None:
    def fake_list() -> list[int]:
        return [101, 202, 303]

    def fake_environ(pid: int) -> dict[str, str]:
        if pid in {101, 202}:
            return {"TDP_RUN_ID": "run-orphan"}
        return {}

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup._read_pid_cmdline",
            side_effect=lambda pid: (
                "agent --output-format stream-json --trust"
                if pid in {101, 202}
                else ""
            ),
        ):
            with patch(
                "top_down_planning.orchestrator.agent_process_cleanup.read_process_start_time",
                return_value="100",
            ):
                orphans = scan_orphan_agent_pids(
                    "run-orphan",
                    terminated_pids=[101],
                    list_live_pids=fake_list,
                    read_pid_environ=fake_environ,
                )
    assert orphans == [101, 202]


def test_scan_orphan_agent_pids_ignores_non_agent_command_with_matching_env() -> None:
    def fake_list() -> list[int]:
        return [303]

    def fake_environ(pid: int) -> dict[str, str]:
        return {"TDP_RUN_ID": "run-orphan"}

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup._read_pid_cmdline",
            return_value="python -c sleep",
        ):
            orphans = scan_orphan_agent_pids(
                "run-orphan",
                list_live_pids=fake_list,
                read_pid_environ=fake_environ,
            )
    assert orphans == []


def test_kill_orphan_agents_emits_audit_event(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T001901-001901")
    run = store.load_run("run-20260101T001901-001901")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PLANNING,
        "message": "cancelled by user",
        "details": {"terminated_pids": [4242]},
    }
    store.save_run("run-20260101T001901-001901", run, expected_revision)

    with patch_identity_safe_orphan_scan("run-20260101T001901-001901", [4242]):
        cleanup = kill_orphan_agents(store, "run-20260101T001901-001901")

    assert cleanup.cleaned_pids == (4242,)
    events = store.load_events("run-20260101T001901-001901")
    assert any(event.get("type") == "agent_orphan_cleaned" for event in events)


def test_teardown_provider_sessions_emits_cancel_audit_events() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[dict[str, object]] = []

    teardown_provider_sessions(
        provider,
        run_id="run-cancel",
        phase=PLANNING,
        append_event=lambda event_type, **fields: events.append(
            {"type": event_type, **fields}
        ),
        emit_console=lambda _event: None,
        audit_cancel=True,
    )

    assert provider.list_active_sessions() == []
    assert any(event["type"] == "planner_session_ended" for event in events)
    ended = next(event for event in events if event["type"] == "planner_session_ended")
    assert ended["session_id"] == session_id


def test_engine_keyboard_interrupt_persists_terminated_pids_and_audit(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)

    class _TrackingProvider(StubProvider):
        def terminate_all_sessions(self) -> list[dict[str, object]]:
            records = [
                {
                    "pid": 9999,
                    "role": "planner",
                    "session_id": "stub-session-1",
                    "reason": "terminated",
                }
            ]
            super().terminate_all_sessions()
            return records

    tracking = _TrackingProvider()
    tracking.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: tracking,
        observability=ObservabilityContext(run_id="run-20260101T001701-001701"),
    )

    def start_session_and_interrupt(self: PlanningPhaseOrchestrator) -> None:
        self._provider.start_primary_session("planner", {"goal": "x"})
        raise KeyboardInterrupt

    with patch.object(PlanningPhaseOrchestrator, "run", start_session_and_interrupt):
        result = engine.continue_run("run-20260101T001701-001701", single_step=True)

    assert result.cancelled is True
    run = store.load_run("run-20260101T001701-001701")
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"
    assert run["stop"]["details"]["terminated_pids"] == [9999]
    events = store.load_events("run-20260101T001701-001701")
    assert any(event.get("type") == "agent_terminated" for event in events)
    assert any(event.get("type") == "planner_session_ended" for event in events)


def test_keyboard_interrupt_after_production_phase_entry_records_production_stop_phase(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION
    from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
    from tests.helpers import whole_plan_approval_record

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001801-001801"
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
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    provider = StubProvider()

    def enter_production_and_interrupt(self: ProductionPhaseOrchestrator) -> None:
        run = store.load_run(run_id)
        expected_revision = int(run["revision"])
        updated = dict(run)
        updated["revision"] = expected_revision + 1
        updated["phase"] = PRODUCTION
        store.save_run(run_id, updated, expected_revision)
        raise KeyboardInterrupt

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
        observability=ObservabilityContext(run_id=run_id),
    )

    with patch.object(ProductionPhaseOrchestrator, "run", enter_production_and_interrupt):
        result = engine.continue_run(run_id, single_step=True)

    assert result.cancelled is True
    assert result.phase == PRODUCTION
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"
    assert run["stop"]["phase"] == PRODUCTION


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_cursor_provider_tracked_turn_procs_killed_on_terminate_all_sessions(
    tmp_path: Path,
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
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    provider._tracked_turn_procs[proc.pid] = ("cursor-session-1", "planner")

    terminated = provider.terminate_all_sessions()

    assert proc.poll() is not None
    assert any(record.get("pid") == proc.pid for record in terminated)


def test_doctor_reports_no_orphan_agents(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T001902-001902")
    run = store.load_run("run-20260101T001902-001902")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PLANNING,
        "message": "cancelled by user",
        "details": {},
    }
    store.save_run("run-20260101T001902-001902", run, expected_revision)

    handle_doctor_command(
        type(
            "Args",
            (),
            {
                "run": "run-20260101T001902-001902",
                "stream_json": False,
                "runs_dir": str(store.root),
                "config": None,
            },
        )()
    )

    assert "no orphan agent processes" in capsys.readouterr().out


def test_doctor_reports_orphan_pids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T001905-001905")

    with patch(
        "top_down_planning.cli.doctor.scan_orphan_agent_pids",
        return_value=[4242, 5151],
    ):
        handle_doctor_command(
            type(
                "Args",
                (),
                {
                    "run": "run-20260101T001905-001905",
                    "stream_json": False,
                    "runs_dir": str(store.root),
                    "config": None,
                },
            )()
        )

    output = capsys.readouterr().out
    assert "2 orphan agent process(es)" in output
    assert "4242" in output
    assert "5151" in output


def test_cursor_provider_terminate_all_sessions_unblocks_stream_events(
    tmp_path: Path,
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
    stream = provider.stream_events(session_id)

    import threading

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.05)
    provider.terminate_all_sessions()
    thread.join(timeout=1)

    assert not thread.is_alive()


def test_run_refuses_orphan_agents_without_force(tmp_path: Path) -> None:
    from top_down_planning.cli.user import handle_run_command
    from tests.helpers import write_config

    config_path = write_config(
        tmp_path / "config.yaml",
        """
version: 1
runtime:
  runs_dir: runs
project:
  workspace: .
run:
  output_goal: Deliver the feature.
planning:
  max_depth: 3
provider:
  name: stub
""",
    )
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    with patch(
        "top_down_planning.cli.user.workspace_has_orphan_agents",
        return_value=[("run-20260101T001904-001904", 9999)],
    ):
        with patch("top_down_planning.cli.user.emit_error_message") as emit_error:
            emit_error.side_effect = (
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    SystemExit(kwargs.get("exit_code", 1))
                )
            )
            with pytest.raises(SystemExit) as exit_info:
                handle_run_command(
                    Namespace(
                        config=str(config_path),
                        set=[],
                        runs_dir=str(runs_root),
                        stream_json=False,
                        force=False,
                        until="plan",
                        command="run",
                    )
                )
            assert exit_info.value.code == 1
            emit_error.assert_called_once()
            assert emit_error.call_args.kwargs["code"] == "orphan_agents_present"


def test_workspace_has_orphan_agents_scans_paused_runs(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T001903-001903")
    run = store.load_run("run-20260101T001903-001903")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PLANNING,
        "message": "cancelled by user",
        "details": {},
    }
    store.save_run("run-20260101T001903-001903", run, expected_revision)

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
        return_value=[5555],
    ):
        orphans = workspace_has_orphan_agents(store)

    assert orphans == [("run-20260101T001903-001903", 5555)]


def test_workspace_has_orphan_agents_scans_stale_running_runs(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-20260101T001906-001906", phase=PLANNING)

    with patch(
        "top_down_planning.domain.run_ownership.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
            return_value=[7777],
        ):
            orphans = workspace_has_orphan_agents(store)

    assert orphans == [("run-20260101T001906-001906", 7777)]


def test_workspace_has_orphan_agents_scans_completed_runs(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001907-001907"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=Plan(
            id=f"plan-{run_id}",
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
        ),
        phase="output_validated",
        **create_run_kwargs(store.root, resolved_config=config),
    )
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["outcome"] = "accepted"
    store.save_run(run_id, run, expected)

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
        return_value=[8888],
    ):
        orphans = workspace_has_orphan_agents(store)

    assert orphans == [(run_id, 8888)]


def test_workspace_has_orphan_agents_scans_failed_runs(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001908-001908"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=Plan(
            id=f"plan-{run_id}",
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
        ),
        phase="production",
        **create_run_kwargs(store.root, resolved_config=config),
    )
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "failed"
    run["stop"] = {
        "code": "orchestrator_invariant_failure",
        "category": "invariant",
        "phase": "production",
        "message": "failed",
    }
    store.save_run(run_id, run, expected)

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
        return_value=[9999],
    ):
        orphans = workspace_has_orphan_agents(store)

    assert orphans == [(run_id, 9999)]
