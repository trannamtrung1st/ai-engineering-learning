"""Slice 5 fifth re-review regression tests (S5-RR5-001 through S5-RR5-005)."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.run_ownership import RunOwnershipError
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.agent_process_cleanup import OrphanCleanupResult
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator, PlanningPhaseResult
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr5",
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


def test_engine_preserves_teardown_pids_when_deferred_signal_replays(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030101-030101"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )

    provider = StubProvider()
    provider.script_turn(done_events(text="ok"))

    def complete_planning(self: PlanningPhaseOrchestrator) -> PlanningPhaseResult:
        return PlanningPhaseResult(
            ok=True,
            phase=PLANNING,
            status="running",
            outcome=None,
            session_id="stub-session",
            agent_turns=1,
            items_added=0,
        )

    def teardown_with_pending_cancel(*_args, **_kwargs) -> list[int]:
        signal.raise_signal(signal.SIGINT)
        return [111]

    with patch.object(PlanningPhaseOrchestrator, "run", complete_planning):
        with patch(
            "top_down_planning.orchestrator.engine.teardown_provider_sessions",
            side_effect=teardown_with_pending_cancel,
        ):
            result = RunEngine(
                store,
                create_provider=lambda _config, _workspace: provider,
            ).continue_run(run_id, single_step=True)

    assert result.cancelled is True
    stored = store.load_run(run_id)
    assert stored["stop"]["details"]["terminated_pids"] == [111]


def test_doctor_fix_holds_run_ownership_during_destructive_repair(
    tmp_path: Path,
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030201-030201"
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

    entered: list[str] = []

    class _Ownership:
        def __enter__(self) -> str:
            entered.append("enter")
            return "token"

        def __exit__(self, *_args: object) -> bool:
            entered.append("exit")
            return False

    with patch(
        "top_down_planning.cli.doctor.run_ownership",
        return_value=_Ownership(),
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=()),
        ) as kill_mock:
            with patch(
                "top_down_planning.cli.doctor.reconcile_stale_running_run_under_ownership",
                return_value=True,
            ):
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

    assert entered == ["enter", "exit"]
    kill_mock.assert_called_once()


def test_doctor_fix_refuses_when_run_ownership_cannot_be_acquired(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030301-030301"
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
        "top_down_planning.cli.doctor.run_ownership",
        side_effect=RunOwnershipError("live owner"),
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=()),
        ) as kill_mock:
            with pytest.raises(SystemExit) as exit_info:
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
            assert exit_info.value.code == 1

    kill_mock.assert_not_called()
    assert "refusing destructive repair" in capsys.readouterr().out.lower()


def test_doctor_fix_releases_ownership_when_repair_raises(tmp_path: Path) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030401-030401"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )

    entered: list[str] = []

    class _Ownership:
        def __enter__(self) -> str:
            entered.append("enter")
            return "token"

        def __exit__(self, *_args: object) -> bool:
            entered.append("exit")
            return False

    with patch(
        "top_down_planning.cli.doctor.run_ownership",
        return_value=_Ownership(),
    ):
        with patch(
            "top_down_planning.cli.doctor.kill_orphan_agents",
            side_effect=RuntimeError("kill failed"),
        ):
            with pytest.raises(RuntimeError, match="kill failed"):
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

    assert entered == ["enter", "exit"]
