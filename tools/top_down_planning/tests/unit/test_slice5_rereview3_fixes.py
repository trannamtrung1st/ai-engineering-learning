"""Slice 5 third re-review regression tests (S5-RR3-001 through S5-RR3-004)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.agent_process_cleanup import (
    OrphanCleanupResult,
    finalize_user_cancel,
    scan_orphan_agent_pids,
)
from top_down_planning.orchestrator.errors import (
    ProviderTeardownError,
    provider_teardown_error_with_final_survivors,
)
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator, PlanningPhaseResult
from top_down_planning.orchestrator.provider_teardown import (
    TeardownVerificationResult,
    verify_run_agent_survivors,
)
from top_down_planning.orchestrator.run_transitions import complete_run_with_outcome
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr3",
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


@pytest.mark.parametrize(
    ("pid", "run_id", "environ", "command", "expected"),
    [
        (101, "run-a", {"TDP_RUN_ID": "run-a"}, _agent_command(), True),
        (101, "run-a", {"TDP_RUN_ID": "run-b"}, _agent_command(), False),
        (101, "run-a", {}, _agent_command(), False),
        (101, "run-a", {"TDP_RUN_ID": "run-a"}, "python -c sleep", False),
    ],
)
def test_scan_orphan_agent_pids_validates_historical_terminated_pids(
    pid: int,
    run_id: str,
    environ: dict[str, str],
    command: str,
    expected: bool,
) -> None:
    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup._read_pid_cmdline",
            return_value=command,
        ):
            orphans = scan_orphan_agent_pids(
                run_id,
                terminated_pids=[pid],
                list_live_pids=lambda: [],
                read_pid_environ=lambda _pid: environ,
            )
    if expected:
        assert orphans == [pid]
    else:
        assert orphans == []


def test_doctor_fix_does_not_kill_reused_unrelated_historical_pid(tmp_path: Path) -> None:
    from top_down_planning.cli.doctor import handle_doctor_command

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010001-010001"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    run = store.load_run(run_id)
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
    store.save_run(run_id, run, expected_revision)

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.terminate_pid_tree",
    ) as terminate:
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
            return_value=True,
        ):
            with patch(
                "top_down_planning.orchestrator.agent_process_cleanup._read_pid_cmdline",
                return_value="python -c sleep",
            ):
                with patch(
                    "top_down_planning.orchestrator.agent_process_cleanup.default_read_pid_environ",
                    return_value={"TDP_RUN_ID": "other-run"},
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

    terminate.assert_not_called()


def test_provider_teardown_error_with_final_survivors_replaces_stale_pids() -> None:
    original = ProviderTeardownError(
        "provider teardown left surviving agent processes: [1234]",
        surviving_pids=(1234,),
    )
    normalized = provider_teardown_error_with_final_survivors(original, ())
    assert normalized.surviving_pids == ()


def test_verify_run_agent_survivors_returns_structured_result(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010101-010101"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )

    with patch(
        "top_down_planning.orchestrator.provider_teardown.kill_orphan_agents",
        return_value=OrphanCleanupResult(cleaned_pids=(1234,), failed_pids=()),
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.scan_orphan_agent_pids",
            return_value=[],
        ):
            result = verify_run_agent_survivors(
                store,
                run_id,
                terminated_pids=[9999],
            )

    assert result == TeardownVerificationResult(
        terminated_pids=(1234, 9999),
        surviving_pids=(),
    )


def test_engine_teardown_fallback_merges_terminated_pids_into_cancel(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010201-010201"
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
                "provider teardown left surviving agent processes: [1234]",
                surviving_pids=(1234,),
            ),
        ):
            with patch(
                "top_down_planning.orchestrator.engine.verify_run_agent_survivors",
                return_value=TeardownVerificationResult(
                    terminated_pids=(1234, 5555),
                    surviving_pids=(),
                ),
            ):
                result = RunEngine(
                    store,
                    create_provider=lambda _config, _workspace: provider,
                ).continue_run(run_id, single_step=True)

    assert result.cancelled is True
    run = store.load_run(run_id)
    assert run["stop"]["details"]["terminated_pids"] == [1234, 5555]
    assert run["stop"]["details"]["cleanup_complete"] is True


def test_engine_completed_run_teardown_failure_escalates_after_deferred_teardown(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010301-010301"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    provider = StubProvider()
    provider.script_turn(done_events(text="ok"))

    def complete_during_planning(self: PlanningPhaseOrchestrator) -> PlanningPhaseResult:
        complete_run_with_outcome(store, run_id, "accepted")
        return PlanningPhaseResult(
            ok=True,
            phase="output_validated",
            status="completed",
            outcome="accepted",
            session_id="stub-session",
            agent_turns=1,
            items_added=0,
        )

    with patch.object(PlanningPhaseOrchestrator, "run", complete_during_planning):
        with patch(
            "top_down_planning.orchestrator.engine.teardown_provider_sessions",
            side_effect=RuntimeError("teardown interrupted"),
        ):
            with patch(
                "top_down_planning.orchestrator.engine.verify_run_agent_survivors",
                return_value=TeardownVerificationResult(
                    terminated_pids=(),
                    surviving_pids=(7777,),
                ),
            ):
                result = RunEngine(
                    store,
                    create_provider=lambda _config, _workspace: provider,
                ).continue_run(run_id, single_step=True)

    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["details"]["surviving_pids"] == [7777]


def test_engine_teardown_uses_deferred_interrupt_signals(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010401-010401"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    provider = StubProvider()
    provider.script_turn(done_events(text="ok"))

    with patch(
        "top_down_planning.orchestrator.engine.defer_run_interrupt_signals",
    ) as defer_mock:
        defer_mock.return_value.__enter__ = lambda *_args, **_kwargs: None
        defer_mock.return_value.__exit__ = lambda *_args, **_kwargs: False
        RunEngine(
            store,
            create_provider=lambda _config, _workspace: provider,
        ).continue_run(run_id, single_step=True)

    defer_mock.assert_called_once()


def test_outer_keyboard_interrupt_reports_incomplete_cleanup(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010501-010501"
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

    with patch.object(
        RunEngine,
        "_continue_run_unlocked",
        side_effect=KeyboardInterrupt,
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.kill_orphan_agents",
            return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(4242,)),
        ):
            with patch(
                "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
                return_value=True,
            ):
                with patch(
                    "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
                    return_value=[],
                ):
                    result = RunEngine(
                        store,
                        create_provider=lambda _config, _workspace: StubProvider(),
                    ).continue_run(run_id, single_step=True)

    assert result.cancelled is True
    assert result.reason == "cancelled by user (agent cleanup incomplete)"


def test_inner_and_outer_cancel_reasons_match_for_incomplete_cleanup(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)

    outer_run_id = "run-20260101T010601-010601"
    store.create_run(
        outer_run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    outer_run = store.load_run(outer_run_id)
    outer_revision = int(outer_run["revision"])
    outer_run = dict(outer_run)
    outer_run["revision"] = outer_revision + 1
    outer_run["status"] = "running"
    store.save_run(outer_run_id, outer_run, outer_revision)

    inner_run_id = "run-20260101T010602-010602"
    store.create_run(
        inner_run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    inner_run = store.load_run(inner_run_id)
    inner_revision = int(inner_run["revision"])
    inner_run = dict(inner_run)
    inner_run["revision"] = inner_revision + 1
    inner_run["status"] = "running"
    store.save_run(inner_run_id, inner_run, inner_revision)

    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.kill_orphan_agents",
        return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(4242,)),
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
            return_value=True,
        ):
            with patch(
                "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
                return_value=[],
            ):
                outer = RunEngine(
                    store,
                    create_provider=lambda _config, _workspace: StubProvider(),
                )
                with patch.object(
                    RunEngine,
                    "_continue_run_unlocked",
                    side_effect=KeyboardInterrupt,
                ):
                    outer_result = outer.continue_run(outer_run_id, single_step=True)

                inner_result = finalize_user_cancel(
                    store,
                    inner_run_id,
                    phase=PLANNING,
                    known_surviving_pids=(4242,),
                )

    assert outer_result.reason == "cancelled by user (agent cleanup incomplete)"
    assert inner_result.cleanup_complete is False
    inner_stored = store.load_run(inner_run_id)
    assert inner_stored["stop"]["details"]["cleanup_complete"] is False
    assert inner_stored["stop"]["details"]["cleanup_failed_pids"] == [4242]
