"""Slice 5 seventh re-review regression tests (S5-RR7-001 through S5-RR7-004)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.agent_process_cleanup import OrphanCleanupResult
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr7",
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


def _doctor_args(
    store: FileRunStore,
    *,
    run_id: str | None,
    fix: bool = True,
    stream_json: bool = False,
) -> object:
    return type(
        "Args",
        (),
        {
            "run": run_id,
            "fix": fix,
            "stream_json": stream_json,
            "runs_dir": str(store.root),
            "config": None,
        },
    )()


def _running_run(store: FileRunStore, run_id: str) -> None:
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


def test_explicit_doctor_repair_fails_closed_when_orphan_cleanup_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050101-050101"
    _running_run(store, run_id)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(7777,)),
        ):
            with patch(
                "top_down_planning.cli.doctor.reconcile_stale_running_run_under_ownership",
            ) as reconcile_mock:
                handle_doctor_command(_doctor_args(store, run_id=run_id))

    reconcile_mock.assert_not_called()
    stored = store.load_run(run_id)
    assert stored["status"] == "running"
    output = capsys.readouterr().out
    assert "7777" in output
    assert "repair incomplete" in output.lower()


def test_explicit_doctor_json_reports_cleanup_failed_pids(tmp_path: Path) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050201-050201"
    _running_run(store, run_id)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(8888,)),
        ):
            with patch("top_down_planning.cli.doctor.emit_payload") as emit_mock:
                handle_doctor_command(
                    _doctor_args(store, run_id=run_id, stream_json=True),
                )

    payload = emit_mock.call_args[0][0]
    assert payload["ok"] is False
    assert payload["reconciled"] is False
    assert payload["repair_incomplete"] is True
    assert payload["cleanup_failed_pids"] == [8888]


def test_workspace_doctor_keeps_surviving_orphan_visible_after_refresh(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050301-050301"
    _running_run(store, run_id)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
            return_value=False,
        ):
            with patch(
                "top_down_planning.orchestrator.run_lifecycle_reconciliation.scan_orphan_agent_pids",
                return_value=[9999],
            ):
                with patch(
                    "top_down_planning.cli.doctor.kill_orphan_agents",
                    return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(9999,)),
                ):
                    handle_doctor_command(_doctor_args(store, run_id=None))

    output = capsys.readouterr().out
    assert run_id in output
    assert "9999" in output
    assert "repair incomplete" in output.lower()


def test_workspace_doctor_json_excludes_cleanup_incomplete_from_reconciled(
    tmp_path: Path,
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050401-050401"
    _running_run(store, run_id)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.orchestrator.run_lifecycle_reconciliation.is_run_orchestrator_alive",
            return_value=False,
        ):
            with patch(
                "top_down_planning.orchestrator.run_lifecycle_reconciliation.scan_orphan_agent_pids",
                return_value=[4242],
            ):
                with patch(
                    "top_down_planning.cli.doctor.kill_orphan_agents",
                    return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(4242,)),
                ):
                    with patch("top_down_planning.cli.doctor.emit_payload") as emit_mock:
                        handle_doctor_command(
                            _doctor_args(store, run_id=None, stream_json=True),
                        )

    payload = emit_mock.call_args[0][0]
    assert run_id not in payload["reconciled_run_ids"]
    assert run_id in payload["repair_incomplete_run_ids"]
    assert payload["cleanup_failed_pids_by_run"][run_id] == [4242]


def test_successful_doctor_repair_still_reconciles_stale_running_run(
    tmp_path: Path,
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050501-050501"
    _running_run(store, run_id)

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(1111,), failed_pids=()),
        ):
            handle_doctor_command(_doctor_args(store, run_id=run_id))

    stored = store.load_run(run_id)
    assert stored["status"] == "paused"
    assert stored["stop"]["code"] == "orchestrator_interrupted"


def test_teardown_reconciles_registry_after_orphan_retry_succeeds(tmp_path: Path) -> None:
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
    events: list[tuple[str, dict]] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append((event_type, dict(fields)))

    alive = {"111": True}
    terminate_attempts: list[int] = []

    def fake_is_alive(pid: int) -> bool:
        return alive.get(str(pid), False)

    def fake_terminate(pid: int) -> bool:
        terminate_attempts.append(pid)
        if len(terminate_attempts) >= 2:
            alive[str(pid)] = False
            return True
        return False

    def mock_terminate_all_sessions() -> list[dict[str, object]]:
        provider._tracked_turn_procs[111] = (session_id, "planner")
        return [
            {
                "pid": 111,
                "role": "planner",
                "session_id": session_id,
                "reason": "termination_failed",
            }
        ]

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T050601-050601"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )

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
                with patch(
                    "top_down_planning.orchestrator.provider_teardown.scan_orphan_agent_pids",
                    side_effect=[[111], []],
                ):
                    with patch.object(
                        provider,
                        "terminate_all_sessions",
                        side_effect=mock_terminate_all_sessions,
                    ):
                        teardown_provider_sessions(
                            provider,
                            run_id=run_id,
                            phase=PLANNING,
                            append_event=append_event,
                            emit_console=lambda _event: None,
                            audit_cancel=True,
                            store=store,
                        )

    assert provider.list_active_sessions() == []
    assert "provider_session_teardown_failed" not in [
        event_type for event_type, _ in events
    ]
    assert [event_type for event_type, _ in events if event_type == "planner_session_ended"] == [
        "planner_session_ended"
    ]


def test_retry_terminate_pids_skips_reused_unrelated_process() -> None:
    from top_down_planning.orchestrator.provider_teardown import _retry_terminate_pids

    terminated: list[int] = []

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_pid_tree",
            side_effect=lambda pid: terminated.append(pid) or True,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.pid_matches_run_agent",
                return_value=False,
            ):
                cleaned, failed = _retry_terminate_pids([4242], run_id="run-a")

    assert cleaned == []
    assert failed == []
    assert terminated == []


def test_retry_terminate_pids_allows_matching_run_agent() -> None:
    from top_down_planning.orchestrator.provider_teardown import _retry_terminate_pids

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.terminate_pid_tree",
            return_value=True,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.pid_matches_run_agent",
                return_value=True,
            ):
                cleaned, failed = _retry_terminate_pids([4242], run_id="run-a")

    assert cleaned == [4242]
    assert failed == []


def test_concurrent_pending_session_starts_get_unique_ids(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    barrier = threading.Barrier(8)
    session_ids: list[str] = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def start_session(index: int) -> None:
        try:
            barrier.wait(timeout=1.0)
            session_id = provider.start_primary_session(
                "planner",
                {"goal": f"goal-{index}"},
            )
            with lock:
                session_ids.append(session_id)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=start_session, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert errors == []
    assert len(session_ids) == len(set(session_ids))
    assert len(provider.list_active_sessions()) == 8


def test_concurrent_durable_resume_does_not_overwrite_session_state(
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
    durable_id = "chat-planner-shared"
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def resume_once() -> None:
        try:
            barrier.wait(timeout=1.0)
            provider.resume_primary_session(
                durable_id,
                {"request": "resume"},
                role="planner",
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=resume_once),
        threading.Thread(target=resume_once),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert errors == []
    assert len(provider.list_active_sessions()) == 1
    session = provider._sessions[durable_id]
    assert session.role == "planner"
    assert session.kind == "primary"
