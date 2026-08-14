"""Slice 5 sixth re-review regression tests (S5-RR6-001 through S5-RR6-005)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import ProcessGroupState
from core_tools.provider.process_identity import ProcessIdentity, TerminateIdentityResult, IdentityInspectState
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.run_ownership import RunOwnershipError, run_ownership
from top_down_planning.orchestrator.agent_process_cleanup import OrphanCleanupResult, PidRunAgentMatch
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.run_lifecycle_reconciliation import (
    reconcile_stale_running_run_under_ownership,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    create_run_kwargs,
    done_events,
    failed_agent_termination_record,
    minimal_resolved_config,
    tracked_turn_proc,
)


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr6",
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


def test_terminate_session_prunes_dead_tracked_pid_after_failed_kill(tmp_path: Path) -> None:
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
    stale_pid = 4242
    provider._tracked_turn_procs[stale_pid] = tracked_turn_proc(session_id, "planner", stale_pid)
    alive = {stale_pid: True}

    def fake_is_alive(pid: int) -> bool:
        return alive.get(pid, False)

    def fake_terminate(_identity, *, proc=None, pgid=None, member_identities=None):
        alive[stale_pid] = False
        return TerminateIdentityResult.FAILED

    with patch("core_tools.provider.cursor.is_pid_alive", side_effect=fake_is_alive):
        with patch(
            "core_tools.provider.cursor.terminate_verified_process_identity",
            side_effect=fake_terminate,
        ):
            provider.terminate_session(session_id)

    assert stale_pid not in provider._tracked_turn_procs
    assert session_id not in provider._sessions


def test_stale_tracked_pid_not_retargeted_after_session_removal(tmp_path: Path) -> None:
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
    stale_pid = 5151
    provider._tracked_turn_procs[stale_pid] = tracked_turn_proc(session_id, "planner", stale_pid)

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=False):
        provider.terminate_session(session_id)

    assert stale_pid not in provider._tracked_turn_procs
    terminate_calls: list[int] = []

    def record_terminate(identity, *, proc=None):
        terminate_calls.append(identity.pid)
        return TerminateIdentityResult.TERMINATED

    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        side_effect=record_terminate,
    ):
        with patch("core_tools.provider.cursor.is_pid_alive", return_value=True):
            provider.terminate_all_sessions()

    assert stale_pid not in terminate_calls


def test_teardown_reconciles_provider_registry_after_retry_success(tmp_path: Path) -> None:
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

    def fake_is_alive(pid: int) -> bool:
        return alive.get(str(pid), False)

    def fake_terminate(pid: int) -> bool:
        alive[str(pid)] = False
        return True

    def mock_terminate_all_sessions() -> list[dict[str, object]]:
        provider._tracked_turn_procs[111] = tracked_turn_proc(session_id, "planner", 111)
        return [
            failed_agent_termination_record(
                session_id,
                "planner",
                111,
                run_id="run-test",
            )
        ]

    def fake_terminate_verified(identity: ProcessIdentity) -> TerminateIdentityResult:
        alive[str(identity.pid)] = False
        return TerminateIdentityResult.TERMINATED

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        side_effect=fake_is_alive,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.classify_pid_run_agent",
            return_value=PidRunAgentMatch.CONFIRMED_SAME,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.read_process_identity",
                return_value=ProcessIdentity(pid=111, start_time="100", run_id="run-test"),
            ):
                with patch(
                    "top_down_planning.orchestrator.provider_teardown.inspect_process_identity",
                    return_value=IdentityInspectState.LIVE_MATCH,
                ):
                    with patch(
                        "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
                        side_effect=fake_terminate_verified,
                    ):
                        with patch.object(
                            provider,
                            "terminate_all_sessions",
                            side_effect=mock_terminate_all_sessions,
                        ):
                            with patch(
                                "top_down_planning.orchestrator.provider_teardown.process_identity_is_live",
                                side_effect=lambda identity: alive.get(
                                    str(identity.pid), False
                                ),
                            ):
                                with patch(
                                    "core_tools.provider.cursor.process_identity_is_live",
                                    side_effect=lambda identity: alive.get(
                                        str(identity.pid), False
                                    ),
                                ):
                                    with patch(
                                        "core_tools.provider.cursor.is_pid_alive",
                                        side_effect=fake_is_alive,
                                    ):
                                        with patch(
                                            "core_tools.provider.cursor.process_group_state",
                                            return_value=ProcessGroupState.GONE,
                                        ):
                                            teardown_provider_sessions(
                                                provider,
                                                run_id="run-test",
                                                phase=PLANNING,
                                                append_event=append_event,
                                                emit_console=lambda _event: None,
                                                audit_cancel=True,
                                            )

    assert provider.list_active_sessions() == []
    ended = [event_type for event_type, _fields in events if event_type == "planner_session_ended"]
    assert ended == ["planner_session_ended"]
    assert "provider_session_teardown_failed" not in [event_type for event_type, _ in events]


def test_reconcile_stale_running_run_under_ownership_pauses_while_repair_lock_held(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.run_lifecycle_reconciliation import (
        reconcile_stale_running_run,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040101-040101"
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
    run_dir = store.run_dir(run_id)

    with run_ownership(run_id, run_dir=run_dir):
        assert reconcile_stale_running_run(store, run_id, require_orphan_agents=False) is False
        assert reconcile_stale_running_run_under_ownership(
            store,
            run_id,
            require_orphan_agents=False,
        ) is True

    stored = store.load_run(run_id)
    assert stored["status"] == "paused"
    assert stored["stop"]["code"] == "orchestrator_interrupted"


def test_explicit_doctor_fix_reconciles_stale_running_run_with_real_ownership(
    tmp_path: Path,
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040201-040201"
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

    with patch(
        "top_down_planning.cli.doctor.is_run_orchestrator_alive",
        return_value=False,
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=()),
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

    kill_mock.assert_called_once()
    stored = store.load_run(run_id)
    assert stored["status"] == "paused"
    assert stored["stop"]["code"] == "orchestrator_interrupted"


def test_workspace_doctor_fix_uses_ownership_safe_repair(tmp_path: Path) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040301-040301"
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
                return_value=[7777],
            ):
                with patch(
                    "top_down_planning.cli.doctor.kill_orphan_agents",
                    return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=()),
                ) as kill_mock:
                    handle_doctor_command(
                        type(
                            "Args",
                            (),
                            {
                                "run": None,
                                "fix": True,
                                "stream_json": False,
                                "runs_dir": str(store.root),
                                "config": None,
                            },
                        )()
                    )

    kill_mock.assert_called_once()


def test_concurrent_migration_and_list_active_sessions_do_not_raise(tmp_path: Path) -> None:
    import threading

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    pending_a = provider.start_primary_session("planner", {"goal": "a"})
    pending_b = provider.start_primary_session("producer", {"goal": "b"})
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def migrate(session_id: str, durable_id: str) -> None:
        try:
            barrier.wait(timeout=0.5)
            provider._maybe_migrate_session(session_id, durable_id)
        except BaseException as exc:
            errors.append(exc)

    def snapshot_active() -> None:
        try:
            barrier.wait(timeout=0.5)
            provider.list_active_sessions()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=migrate, args=(pending_a, "chat-planner-1")),
        threading.Thread(target=snapshot_active),
        threading.Thread(target=migrate, args=(pending_b, "chat-producer-1")),
        threading.Thread(target=snapshot_active),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=0.5)

    assert errors == []
