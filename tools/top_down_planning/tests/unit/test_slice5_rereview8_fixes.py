"""Slice 5 eighth re-review regression tests (S5-RR8-001 through S5-RR8-003)."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError
from core_tools.provider.process_identity import ProcessIdentity
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.agent_process_cleanup import (
    PidRunAgentMatch,
    classify_pid_run_agent,
    kill_orphan_agents,
    scan_orphan_agents,
)
from top_down_planning.orchestrator.errors import ProviderTeardownError as OrchestratorTeardownError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import (
    RetryTerminateResult,
    _retry_terminate_pids,
    teardown_provider_sessions,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr8",
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


def test_retry_terminate_pids_marks_unverifiable_alive_pid_as_unresolved() -> None:
    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.classify_pid_run_agent",
            return_value=PidRunAgentMatch.UNVERIFIABLE,
        ):
            result = _retry_terminate_pids([4242], run_id="run-a")

    assert result == RetryTerminateResult(
        terminated=(),
        failed=(),
        unresolved=(4242,),
        stale_reconciled=(),
    )


def test_retry_terminate_pids_reconciles_confirmed_different_pid_without_killing() -> None:
    terminated: list[int] = []

    with patch(
        "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.classify_pid_run_agent",
            return_value=PidRunAgentMatch.CONFIRMED_DIFFERENT,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.terminate_pid_tree",
                side_effect=lambda pid: terminated.append(pid) or True,
            ):
                result = _retry_terminate_pids([4242], run_id="run-a")

    assert result.stale_reconciled == (4242,)
    assert terminated == []


def test_teardown_fails_closed_when_failed_pid_identity_is_unverifiable(tmp_path: Path) -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    with patch.object(
        provider,
        "terminate_all_sessions",
        return_value=[
            {
                "pid": 4242,
                "role": "planner",
                "session_id": session_id,
                "reason": "termination_failed",
            }
        ],
    ):
        with patch(
            "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
            return_value=True,
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.classify_pid_run_agent",
                return_value=PidRunAgentMatch.UNVERIFIABLE,
            ):
                with pytest.raises(OrchestratorTeardownError, match="surviving agent processes"):
                    teardown_provider_sessions(
                        provider,
                        run_id="run-rr8",
                        phase=PLANNING,
                        append_event=lambda *_args, **_kwargs: None,
                        emit_console=lambda _event: None,
                    )

    assert provider.list_active_sessions()


def test_teardown_requires_provider_sessions_inactive_on_success(tmp_path: Path) -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    provider.start_primary_session("planner", {"goal": "x"})

    with patch.object(provider, "terminate_all_sessions", return_value=[]):
        with patch.object(provider, "list_active_sessions", return_value=[{"session_id": "still-active", "role": "planner", "kind": "primary"}]):
            with pytest.raises(OrchestratorTeardownError, match="active sessions"):
                teardown_provider_sessions(
                    provider,
                    run_id="run-rr8",
                    phase=PLANNING,
                    append_event=lambda *_args, **_kwargs: None,
                    emit_console=lambda _event: None,
                )


def test_kill_orphan_agents_does_not_signal_pid_reused_before_termination(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020001-020001"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    identity = ProcessIdentity(pid=4242, start_time="100", run_id=run_id)

    from core_tools.provider.process_identity import TerminateIdentityResult
    from tests.helpers import patch_identity_safe_orphan_scan

    with patch_identity_safe_orphan_scan(
        run_id,
        [4242],
        terminate_result=TerminateIdentityResult.IDENTITY_MISMATCH,
    ):
        cleanup = kill_orphan_agents(store, run_id)

    assert cleanup.cleaned_pids == ()
    assert cleanup.failed_pids == ()


def test_classify_pid_run_agent_requires_start_time_for_confirmed_same() -> None:
    with patch(
        "top_down_planning.orchestrator.agent_process_cleanup.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "top_down_planning.orchestrator.agent_process_cleanup.default_read_pid_environ",
            return_value={"TDP_RUN_ID": "run-a"},
        ):
            with patch(
                "top_down_planning.orchestrator.agent_process_cleanup._read_pid_cmdline",
                return_value="agent --output-format stream-json --trust",
            ):
                with patch(
                    "top_down_planning.orchestrator.agent_process_cleanup.read_process_start_time",
                    return_value=None,
                ):
                    assert (
                        classify_pid_run_agent("run-a", 4242)
                        == PidRunAgentMatch.UNVERIFIABLE
                    )


def test_concurrent_durable_resume_rejects_second_queued_turn(tmp_path: Path) -> None:
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
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

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

    turn_errors = [exc for exc in errors if isinstance(exc, ProviderTurnError)]
    assert len(turn_errors) == 1
    assert "already queued" in str(turn_errors[0])
    session = provider._sessions[durable_id]
    assert session.pending_argv is not None
