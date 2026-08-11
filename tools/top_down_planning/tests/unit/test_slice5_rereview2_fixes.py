"""Slice 5 second re-review regression tests (S5-RR2-001 through S5-RR2-005)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionError
from core_tools.provider.cursor import CursorProvider, _STDERR_TAIL_MAX_BYTES
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.agent_process_cleanup import finalize_user_cancel
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.run_transitions import complete_run_with_outcome
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr2",
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


def test_finalize_user_cancel_persists_cleanup_failed_pids(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009001-009001"
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
        "top_down_planning.orchestrator.agent_process_cleanup.kill_orphan_agents",
    ) as kill_mock:
        from top_down_planning.orchestrator.agent_process_cleanup import OrphanCleanupResult

        kill_mock.return_value = OrphanCleanupResult(cleaned_pids=(), failed_pids=(4242,))
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
            return_value=True,
        ):
            with patch(
                "top_down_planning.orchestrator.agent_process_cleanup.scan_orphan_agent_pids",
                return_value=[],
            ):
                result = finalize_user_cancel(
                    store,
                    run_id,
                    phase=PLANNING,
                    known_surviving_pids=(9999,),
                )

    assert result.cleanup_complete is False
    assert result.surviving_pids == (4242, 9999)
    run = store.load_run(run_id)
    assert run["stop"]["details"]["cleanup_failed_pids"] == [4242, 9999]
    assert run["stop"]["details"]["cleanup_complete"] is False


def test_engine_teardown_runtime_error_does_not_proceed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009101-009101"
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
    provider.script_turn(done_events(signal="candidate_plan_ready"))

    with patch(
        "top_down_planning.orchestrator.engine.teardown_provider_sessions",
        side_effect=RuntimeError("terminate_all_sessions exploded"),
    ):
        with patch(
            "top_down_planning.orchestrator.engine.verify_run_agent_survivors",
            return_value=__import__(
                "top_down_planning.orchestrator.provider_teardown",
                fromlist=["TeardownVerificationResult"],
            ).TeardownVerificationResult(
                terminated_pids=(),
                surviving_pids=(8888,),
            ),
        ):
            result = RunEngine(
                store,
                create_provider=lambda _config, _workspace: provider,
            ).continue_run(run_id, single_step=True)

    assert result.ok is False
    assert "terminate_all_sessions exploded" in (result.reason or "")
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["details"]["surviving_pids"] == [8888]


def test_apply_provider_teardown_failure_escalates_completed_run(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.engine import _apply_provider_teardown_failure
    from top_down_planning.orchestrator.errors import ProviderTeardownError

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009201-009201"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    complete_run_with_outcome(store, run_id, "accepted")

    _apply_provider_teardown_failure(
        store,
        run_id,
        phase=PLANNING,
        teardown_failed=ProviderTeardownError(
            "provider teardown left surviving agent processes: [7777]",
            surviving_pids=(7777,),
        ),
    )

    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["details"]["surviving_pids"] == [7777]


def test_stub_send_rejects_primary_session() -> None:
    provider = StubProvider()
    provider.script_turn(done_events(text="ok"))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderSessionError, match="send\\(\\) is only supported for reviewer"):
        provider.send(session_id, {"action": "nope"})


def test_cursor_send_rejects_warm_primary_session(tmp_path: Path) -> None:
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
    with pytest.raises(ProviderSessionError, match="send\\(\\) is only supported for reviewer"):
        provider.send(session_id, {"action": "nope"})


def test_default_process_runner_bounds_stderr_by_bytes(tmp_path: Path) -> None:
    import json
    import sys

    from core_tools.provider.cursor import _SubprocessStdoutIterator, default_process_runner

    script = tmp_path / "chatty_stderr_bytes.py"
    script.write_text(
        "import json, sys\n"
        f"sys.stderr.buffer.write(b'x' * {_STDERR_TAIL_MAX_BYTES + 10_000})\n"
        "sys.stderr.flush()\n"
        'print(json.dumps({"type": "assistant", "text": "ok"}))\n'
        'print(json.dumps({"type": "result", "subtype": "success", "text": "ok", "is_error": False}))\n',
        encoding="utf-8",
    )
    argv = [sys.executable, str(script)]
    iterator = default_process_runner(argv, tmp_path)
    assert isinstance(iterator, _SubprocessStdoutIterator)
    list(iterator)
    assert iterator._stderr_truncated is True
    assert len(iterator._stderr_tail) <= _STDERR_TAIL_MAX_BYTES
