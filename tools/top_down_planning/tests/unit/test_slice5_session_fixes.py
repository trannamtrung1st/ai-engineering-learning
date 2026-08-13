"""Slice 5 regression tests for provider session and teardown fixes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import ProviderTurnStalledError
from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError
from core_tools.provider.stub import StubProvider
from top_down_planning.config import resolve_effective_activity_context
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.agent_process_cleanup import finalize_user_cancel
from top_down_planning.orchestrator.phases import PLANNING, PLAN_AMENDMENT
from top_down_planning.orchestrator.plan_amendment import PlanAmendmentOrchestrator
from top_down_planning.orchestrator.errors import ProviderTeardownError
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.session_context import rotate_primary_session
from top_down_planning.orchestrator.session_events import (
    end_primary_session_with_audit,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import update_primary_binding
from tests.helpers import create_run_kwargs, done_events, minimal_resolved_config, tracked_turn_proc, write_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5",
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


def _nested_config_yaml() -> str:
    return """
run:
  output_goal: Goal.
agent_context:
  default:
    model: auto
  roles:
    planner:
      resources: []
      skills: []
    producer:
      resources: []
      skills: []
    reviewer:
      resources: []
      skills: []
  activities:
    initial_plan:
      model: smart
    plan_amendment:
      model: smart
    production:
      model: medium
"""


def _create_run(store: FileRunStore, run_id: str, config: dict) -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=config),
    )


def _bind_planner(
    store: FileRunStore,
    run_id: str,
    *,
    session_id: str,
    activity: str,
    context_digest: str,
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
        activity=activity,
        context_digest=context_digest,
    )
    store.save_run(run_id, run, expected_revision)


def test_amendment_resume_planner_does_not_pass_unsupported_keywords(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007101-007101"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = PLAN_AMENDMENT
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    activity_context = resolve_effective_activity_context(
        config,
        "planner",
        "plan_amendment",
        workspace=workspace,
    )
    provider.script_turn(done_events(text="planner start"))
    session_id = provider.start_primary_session(
        "planner",
        {"phase": PLAN_AMENDMENT},
        model=activity_context.model,
    )
    list(provider.stream_events(session_id))
    _bind_planner(
        store,
        run_id,
        session_id=session_id,
        activity=activity_context.activity,
        context_digest=activity_context.context_digest,
    )

    production = dict(store.load_production(run_id))
    production["pending_amendment_id"] = "amendment-01"
    production["amendment_requests"] = [
        {
            "id": "amendment-01",
            "status": "pending",
            "evidence": "gap",
            "affected_refs": ["item-root"],
            "summary": "fix plan",
        }
    ]
    production["revision"] = int(production["revision"]) + 1
    store.save_production(run_id, production, int(production["revision"]) - 1)

    provider.script_session_turn(session_id, done_events(text="amendment resume"))
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    amendment = production["amendment_requests"][0]
    resumed_id = orch._resume_planner_for_amendment(amendment)
    assert resumed_id == session_id


def test_rotate_primary_with_handoff_starts_fresh_not_resume(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007102-007102"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)

    provider = StubProvider()
    requested = resolve_effective_activity_context(
        config,
        "planner",
        "plan_amendment",
        workspace=workspace,
    )
    manifest = {"phase": PLAN_AMENDMENT, "goal": "amend"}
    handoff = {"action": "revise_for_amendment", "phase": PLAN_AMENDMENT}

    provider.script_turn(done_events(text="old session"))
    old_session_id = provider.start_primary_session("planner", manifest, model=requested.model)
    list(provider.stream_events(old_session_id))

    provider.script_turn(done_events(text="fresh session"))
    events: list[str] = []

    new_session_id = rotate_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLAN_AMENDMENT,
        old_provider_session_id=old_session_id,
        requested=requested,
        manifest=manifest,
        append_event=lambda event_type, **_fields: events.append(event_type),
        handoff_request=handoff,
    )

    assert new_session_id != old_session_id
    assert not str(new_session_id).startswith("tdp-session-")
    old_session = provider._sessions.get(old_session_id)
    new_session = provider._sessions.get(new_session_id)
    assert old_session is None
    assert new_session is not None
    assert new_session.history[0].get("kind") == "start"
    assert "planner_session_ended" in events
    assert "planner_session_started" in events


def test_cold_resume_preserves_planner_role(tmp_path: Path) -> None:
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "chat-planner-1"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-planner-1",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    list(provider.stream_events(session_id))
    canonical_id = provider.canonical_session_id(session_id)
    provider.terminate_all_sessions()

    provider.resume_primary_session(canonical_id, {"action": "continue"}, role="planner")
    list(provider.stream_events(canonical_id))

    ref = provider.get_session_reference(canonical_id)
    assert ref["role"] == "planner"
    active = provider.list_active_sessions()
    assert active[0]["role"] == "planner"


def test_cold_resume_preserves_producer_role(tmp_path: Path) -> None:
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "chat-producer-1"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-producer-1",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "build"})
    list(provider.stream_events(session_id))
    canonical_id = provider.canonical_session_id(session_id)
    provider.terminate_all_sessions()

    provider.resume_primary_session(canonical_id, {"action": "continue"}, role="producer")
    list(provider.stream_events(canonical_id))

    assert provider.get_session_reference(canonical_id)["role"] == "producer"


def test_end_primary_session_with_audit_emits_failure_when_terminate_raises() -> None:
    class FailingProvider(StubProvider):
        def terminate_session(self, session_id: str) -> None:
            raise RuntimeError("terminate failed")

    provider = FailingProvider()
    provider.script_turn(done_events(text="ok"))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[str] = []

    end_primary_session_with_audit(
        lambda event_type, **_fields: events.append(event_type),
        provider,
        role="planner",
        phase=PLANNING,
        session_id=session_id,
    )

    assert "planner_session_ended" not in events
    assert "provider_session_teardown_failed" in events


def test_finalize_user_cancel_persists_orphan_pids_in_stop_details(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007103-007103"
    _create_run(store, run_id, minimal_resolved_config())
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    store.save_run(run_id, run, expected_revision)

    from tests.helpers import patch_identity_safe_orphan_scan

    with patch_identity_safe_orphan_scan(run_id, [4242]):
        finalize_user_cancel(
            store,
            run_id,
            phase=PLANNING,
            provider_terminated_pids=[],
        )

    run = store.load_run(run_id)
    assert run["stop"]["details"]["terminated_pids"] == [4242]


def test_provider_turn_stalled_error_is_exported() -> None:
    from core_tools.provider import ProviderTurnStalledError as exported

    assert exported is ProviderTurnStalledError


def test_cursor_resume_rejects_unexpected_durable_session_id(tmp_path: Path) -> None:
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "chat-abc"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-xyz",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    list(provider.stream_events(session_id))
    canonical_id = provider.canonical_session_id(session_id)
    provider.terminate_all_sessions()
    provider.resume_primary_session(canonical_id, {"action": "continue"}, role="planner")

    with pytest.raises(ProviderTurnError, match="unexpected session id"):
        list(provider.stream_events(canonical_id))


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_cursor_provider_tracks_pid_before_first_stdout(tmp_path: Path) -> None:
    from core_tools.provider.cursor import default_process_runner

    agent_path = tmp_path / "agent"
    agent_path.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    agent_path.chmod(0o755)

    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=default_process_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    import threading
    import time

    tracked_pid: int | None = None
    unexpected_errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(provider.stream_events(session_id))
        except ProviderTurnError:
            # Expected when terminate_all_sessions() stops the tracked turn.
            pass
        except BaseException as exc:
            unexpected_errors.append(exc)

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2.0
    while tracked_pid is None and time.monotonic() < deadline:
        with provider._turn_proc_lock:
            if provider._tracked_turn_procs:
                tracked_pid = next(iter(provider._tracked_turn_procs))
        time.sleep(0.01)

    assert tracked_pid is not None
    provider.terminate_all_sessions()
    thread.join(timeout=1.0)
    assert thread.is_alive() is False
    assert unexpected_errors == []


def test_amendment_starts_fresh_planner_when_unbound(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007104-007104"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = PLAN_AMENDMENT
    store.save_run(run_id, run, expected_revision)

    production = dict(store.load_production(run_id))
    production["pending_amendment_id"] = "amendment-01"
    production["amendment_requests"] = [
        {
            "id": "amendment-01",
            "status": "pending",
            "evidence": "gap",
            "affected_refs": ["item-root"],
            "summary": "fix plan",
        }
    ]
    production["revision"] = int(production["revision"]) + 1
    store.save_production(run_id, production, int(production["revision"]) - 1)

    provider = StubProvider()
    provider.script_turn(done_events(text="fresh amendment planner"))
    orch = PlanAmendmentOrchestrator(store, run_id, provider)
    session_id = orch._resume_planner_for_amendment(production["amendment_requests"][0])

    session = provider._sessions[session_id]
    assert session.history[0].get("kind") == "start"
    assert session.role == "planner"


def test_rotate_primary_handoff_does_not_record_replacement_attempt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007105-007105"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)

    provider = StubProvider()
    requested = resolve_effective_activity_context(
        config,
        "planner",
        "plan_amendment",
        workspace=workspace,
    )
    manifest = {"phase": PLAN_AMENDMENT, "goal": "amend"}
    handoff = {"action": "revise_for_amendment", "phase": PLAN_AMENDMENT}

    provider.script_turn(done_events(text="old session"))
    old_session_id = provider.start_primary_session("planner", manifest, model=requested.model)
    list(provider.stream_events(old_session_id))
    _bind_planner(
        store,
        run_id,
        session_id=old_session_id,
        activity="initial_plan",
        context_digest="digest-a",
    )

    provider.script_turn(done_events(text="fresh session"))
    events: list[str] = []
    rotate_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLAN_AMENDMENT,
        old_provider_session_id=old_session_id,
        requested=requested,
        manifest=manifest,
        append_event=lambda event_type, **_fields: events.append(event_type),
        handoff_request=handoff,
        phase_action_id="action-rotate-01",
    )

    run = store.load_run(run_id)
    assert run.get("session_replacement_phase_action_id") is None
    assert "session_resume_failed" not in events


def test_rotate_primary_handoff_omits_resume_argv(tmp_path: Path) -> None:
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "chat-fresh-1"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-fresh-1",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]
    captured_argv: list[list[str]] = []

    def fake_runner(argv: list[str], cwd: Path):
        captured_argv.append(list(argv))
        for line in stream_lines:
            yield line

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007106-007106"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=workspace,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    requested = resolve_effective_activity_context(
        config,
        "planner",
        "plan_amendment",
        workspace=workspace,
    )
    manifest = {"phase": PLAN_AMENDMENT, "goal": "amend"}
    handoff = {"action": "revise_for_amendment", "phase": PLAN_AMENDMENT}

    old_session_id = provider.start_primary_session("planner", manifest, model=requested.model)
    list(provider.stream_events(old_session_id))
    _bind_planner(
        store,
        run_id,
        session_id=old_session_id,
        activity="initial_plan",
        context_digest="digest-a",
    )

    rotate_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLAN_AMENDMENT,
        old_provider_session_id=old_session_id,
        requested=requested,
        manifest=manifest,
        append_event=lambda *_args, **_kwargs: None,
        handoff_request=handoff,
    )
    list(provider.stream_events(provider.list_active_sessions()[0]["session_id"]))

    assert captured_argv
    assert "--resume" not in captured_argv[-1]
    assert not any(arg.startswith("tdp-session-") for arg in captured_argv[-1])


def test_teardown_provider_sessions_emits_agent_termination_failed_not_terminated(
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
    proc = __import__("subprocess").Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=__import__("subprocess").DEVNULL,
        stderr=__import__("subprocess").DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc("cursor-session-1", "planner", proc.pid, proc=proc)

    events: list[dict[str, object]] = []

    from core_tools.provider.process_identity import ProcessIdentity, TerminateIdentityResult
    from top_down_planning.orchestrator.agent_process_cleanup import PidRunAgentMatch

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
                        run_id="run-cancel",
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
                            with pytest.raises(ProviderTeardownError):
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
    finally:
        proc.kill()
        proc.wait(timeout=1)

    assert not any(event["type"] == "agent_terminated" for event in events)
    assert any(event["type"] == "agent_termination_failed" for event in events)


def test_cold_resume_cancel_emits_producer_session_ended(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.session_events import end_primary_session_with_audit

    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "chat-producer-2"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-producer-2",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "build"})
    list(provider.stream_events(session_id))
    canonical_id = provider.canonical_session_id(session_id)
    provider.terminate_all_sessions()
    provider.resume_primary_session(canonical_id, {"action": "continue"}, role="producer")
    list(provider.stream_events(canonical_id))

    events: list[str] = []
    end_primary_session_with_audit(
        lambda event_type, **_fields: events.append(event_type),
        provider,
        role="producer",
        phase=PLANNING,
        session_id=canonical_id,
    )
    assert events == ["producer_session_ended"]
