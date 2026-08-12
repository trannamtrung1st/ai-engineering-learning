"""Slice 5 re-review regression tests (S5-RR-001 through S5-RR-006)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _STDERR_TAIL_MAX_BYTES
from core_tools.provider.errors import ProviderSessionError
from core_tools.provider.stub import StubProvider
from top_down_planning.config import resolve_effective_activity_context
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProviderRunError, RunEngine
from top_down_planning.orchestrator.agent_process_cleanup import (
    OrphanCleanupResult,
    finalize_user_cancel,
)
from core_tools.provider.process_identity import ProcessIdentity, TerminateIdentityResult
from top_down_planning.orchestrator.agent_process_cleanup import PidRunAgentMatch
from top_down_planning.orchestrator.errors import ProviderTeardownError
from top_down_planning.orchestrator.phases import PLANNING, PLAN_AMENDMENT
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.session_context import rotate_primary_session
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import update_primary_binding
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-rr",
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


def _bind_planner(
    store: FileRunStore,
    run_id: str,
    *,
    session_id: str,
) -> None:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = update_primary_binding(
        dict(run.get("sessions") or {}),
        role="planner",
        provider_session_id=session_id,
        provider="cursor",
        activity="initial_plan",
        context_digest="digest-a",
    )
    store.save_run(run_id, run, expected_revision)


@pytest.mark.parametrize("role", ["planner", "producer"])
def test_stub_warm_resume_matching_role_succeeds(role: str) -> None:
    provider = StubProvider()
    provider.script_turn(done_events(text="start"))
    provider.script_turn(done_events(text="resume"))
    session_id = provider.start_primary_session(role, {"goal": "x"})
    provider.resume_primary_session(session_id, {"goal": "follow-up"}, role=role)
    assert provider.get_session_reference(session_id)["role"] == role


@pytest.mark.parametrize(
    ("start_role", "resume_role"),
    [("producer", "planner"), ("planner", "producer")],
)
def test_stub_warm_resume_role_mismatch_fails(
    start_role: str,
    resume_role: str,
) -> None:
    provider = StubProvider()
    provider.script_turn(done_events(text="ok"))
    session_id = provider.start_primary_session(start_role, {"goal": "x"})
    with pytest.raises(ProviderSessionError, match="role/kind mismatch"):
        provider.resume_primary_session(session_id, {"goal": "follow-up"}, role=resume_role)


def test_cursor_warm_resume_role_mismatch_fails(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    durable_id = "chat-producer-warm"
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": durable_id}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": durable_id,
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        for line in stream_lines:
            yield line

    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    list(provider.stream_events(session_id))
    with pytest.raises(ProviderSessionError, match="role/kind mismatch"):
        provider.resume_primary_session(
            provider.canonical_session_id(session_id),
            {"goal": "follow-up"},
            role="planner",
        )


def test_rotate_primary_session_aborts_when_old_session_teardown_fails(
    tmp_path: Path,
) -> None:
    class StickyProvider(StubProvider):
        def terminate_session(self, session_id: str) -> None:
            return

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T008001-008001"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    provider = StickyProvider()
    provider.script_turn(done_events(text="ok"))
    provider.script_turn(done_events(text="ok"))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    _bind_planner(store, run_id, session_id=session_id)
    revision_before = int(store.load_run(run_id)["revision"])
    config = minimal_resolved_config()
    requested = resolve_effective_activity_context(
        config,
        "planner",
        "plan_amendment",
        workspace=tmp_path,
    )

    with pytest.raises(ProviderRunError, match="teardown failed"):
        rotate_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase=PLAN_AMENDMENT,
            old_provider_session_id=session_id,
            requested=requested,
            manifest={"goal": "x"},
            append_event=lambda *_args, **_kwargs: None,
        )

    assert len(provider.list_active_sessions()) == 1
    assert int(store.load_run(run_id)["revision"]) == revision_before


def test_finalize_user_cancel_keeps_verified_pid_when_audit_append_fails(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T008101-008101"
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

    original_append = store.append_event

    def flaky_append(run_id_arg: str, event: dict) -> None:
        if event.get("type") == "agent_orphan_cleaned":
            raise RuntimeError("audit persistence failed")
        original_append(run_id_arg, event)

    from tests.helpers import patch_identity_safe_orphan_scan

    with patch.object(store, "append_event", side_effect=flaky_append):
        with patch_identity_safe_orphan_scan(run_id, [4242]):
            finalize_user_cancel(
                store,
                run_id,
                phase=PLANNING,
                provider_terminated_pids=[],
            )

    run = store.load_run(run_id)
    assert run["stop"]["details"]["terminated_pids"] == [4242]


def test_engine_blocks_provider_when_pre_run_orphan_cleanup_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T008201-008201"
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
    run["phase"] = PLANNING
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    provider.script_turn(done_events(signal="candidate_plan_ready"))

    def _forbidden_factory(_config: object, _workspace: object) -> StubProvider:
        raise AssertionError("create_provider must not run when orphan cleanup fails")

    with patch(
        "top_down_planning.orchestrator.engine.kill_orphan_agents",
        return_value=OrphanCleanupResult(cleaned_pids=(), failed_pids=(9999,)),
    ):
        result = RunEngine(
            store,
            create_provider=_forbidden_factory,
        ).continue_run(run_id, single_step=True)

    assert result.ok is False
    assert store.load_run(run_id)["status"] == "failed"


def test_teardown_provider_sessions_raises_when_survivors_remain(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    proc = __import__("subprocess").Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=__import__("subprocess").DEVNULL,
        stderr=__import__("subprocess").DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = ("cursor-session-1", "planner")

    events: list[dict[str, object]] = []
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T008301-008301"
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )

    try:
        with patch.object(
            provider,
            "terminate_all_sessions",
            return_value=[
                {
                    "pid": proc.pid,
                    "role": "planner",
                    "session_id": "cursor-session-1",
                    "reason": "termination_failed",
                }
            ],
        ):
            with patch(
                "top_down_planning.orchestrator.provider_teardown.classify_pid_run_agent",
                return_value=PidRunAgentMatch.CONFIRMED_SAME,
            ):
                with patch(
                    "top_down_planning.orchestrator.provider_teardown.read_process_identity",
                    return_value=ProcessIdentity(
                        pid=proc.pid,
                        start_time="100",
                        run_id=run_id,
                    ),
                ):
                    with patch(
                        "top_down_planning.orchestrator.provider_teardown.terminate_verified_process_identity",
                        return_value=TerminateIdentityResult.FAILED,
                    ):
                        with patch(
                            "top_down_planning.orchestrator.provider_teardown.is_pid_alive",
                            return_value=True,
                        ):
                            with pytest.raises(ProviderTeardownError) as exc_info:
                                teardown_provider_sessions(
                                    provider,
                                    run_id=run_id,
                                    phase=PLANNING,
                                    append_event=lambda event_type, **fields: events.append(
                                        {"type": event_type, **fields}
                                    ),
                                    emit_console=lambda _event: None,
                                    store=store,
                                )
                            assert proc.pid in exc_info.value.surviving_pids
                            assert any(
                                event["type"] == "agent_termination_failed" for event in events
                            )
    finally:
        proc.kill()
        proc.wait(timeout=1)


def test_default_process_runner_bounds_retained_stderr(tmp_path: Path) -> None:
    from core_tools.provider.cursor import (
        _SubprocessStdoutIterator,
        default_process_runner,
    )

    script = tmp_path / "chatty_stderr_lines.py"
    script.write_text(
        "import json, sys\n"
        "for i in range(5000):\n"
        "    sys.stderr.write('x' * 20 + '\\n')\n"
        "sys.stderr.flush()\n"
        'print(json.dumps({"type": "assistant", "text": "ok"}))\n'
        'print(json.dumps({"type": "result", "subtype": "success", "text": "ok", "is_error": False}))\n',
        encoding="utf-8",
    )
    argv = [__import__("sys").executable, str(script)]
    iterator = default_process_runner(argv, tmp_path)
    assert isinstance(iterator, _SubprocessStdoutIterator)
    lines = list(iterator)
    assert lines
    assert iterator._stderr_truncated is True
    assert len(iterator._stderr_tail) <= _STDERR_TAIL_MAX_BYTES
