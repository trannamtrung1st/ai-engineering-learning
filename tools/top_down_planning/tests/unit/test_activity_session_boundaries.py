"""Activity-aware primary session boundary tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from top_down_planning.config import EffectiveActivityContext, resolve_effective_activity_context
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.orchestrator.activity_context import session_continuation_decision
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    update_primary_binding,
)
from core_tools.provider import StubProvider
from tests.helpers import create_run_kwargs, done_events, write_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-activity-session",
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


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _nested_config_yaml(*, planner_initial_model: str = "smart", planner_revision_model: str = "medium") -> str:
    return f"""
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
      model: {planner_initial_model}
    plan_revision:
      model: {planner_revision_model}
    plan_amendment:
      model: smart
    production:
      model: medium
    output_revision:
      model: medium
    initial_review:
      model: smart
    finding_verification:
      model: smart
    scope_review:
      model: smart
"""


def _create_run(store: FileRunStore, run_id: str, config: dict) -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=config),
    )


def _resolved_context(
    config: dict,
    workspace: Path,
    role: str,
    activity: str,
) -> EffectiveActivityContext:
    return resolve_effective_activity_context(
        config,
        role,
        activity,
        workspace=workspace,
    )


def _bind_primary_with_activity(
    store: FileRunStore,
    run_id: str,
    *,
    role: str,
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
        role=role,
        provider_session_id=session_id,
        provider="cursor",
        activity=activity,
        context_digest=context_digest,
    )
    store.save_run(run_id, run, expected_revision)


def _requested_context(
    role: str,
    activity: str,
    context_digest: str,
) -> EffectiveActivityContext:
    return EffectiveActivityContext(
        role=role,
        activity=activity,
        model="test-model",
        input_refs=(),
        output_goal="Goal.",
        guidance=(),
        resources=(),
        skills=(),
        context_digest=context_digest,
    )


def test_session_continuation_decision_resumes_matching_bound_context() -> None:
    binding = new_session_binding(role="planner", kind="primary", state="unbound")
    binding = binding.with_provider_session_id("cursor-abc")
    binding = replace(binding, activity="initial_plan", context_digest="digest-a")
    requested = _requested_context("planner", "initial_plan", "digest-a")
    assert session_continuation_decision(binding, requested) == "resume"


def test_session_continuation_decision_fresh_on_activity_change() -> None:
    binding = new_session_binding(role="planner", kind="primary", state="unbound")
    binding = binding.with_provider_session_id("cursor-abc")
    binding = replace(binding, activity="initial_plan", context_digest="digest-a")
    requested = _requested_context("planner", "plan_revision", "digest-a")
    assert session_continuation_decision(binding, requested) == "fresh"


def test_session_continuation_decision_fresh_on_digest_change() -> None:
    binding = new_session_binding(role="planner", kind="primary", state="unbound")
    binding = binding.with_provider_session_id("cursor-abc")
    binding = replace(binding, activity="initial_plan", context_digest="digest-a")
    requested = _requested_context("planner", "initial_plan", "digest-b")
    assert session_continuation_decision(binding, requested) == "fresh"


def test_same_activity_resumes_primary_session(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)

    provider = StubProvider()
    requested = _resolved_context(config, workspace, "planner", "initial_plan")
    manifest = {"phase": PLANNING, "goal": "plan"}

    provider.script_turn(done_events(text="planner start"))
    old_session_id = provider.start_primary_session(
        "planner",
        manifest,
        model=requested.model,
    )
    list(provider.stream_events(old_session_id))
    _bind_primary_with_activity(
        store,
        run_id,
        role="planner",
        session_id=old_session_id,
        activity=requested.activity,
        context_digest=requested.context_digest,
    )

    provider.script_session_turn(old_session_id, done_events(text="planner resume"))
    events: list[str] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append(event_type)

    session_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLANNING,
        requested=requested,
        manifest=manifest,
        append_event=append_event,
        resume_request={"action": "continue", "phase": PLANNING},
    )

    assert session_id == old_session_id
    assert "planner_session_ended" not in events
    assert "planner_session_resumed" in events
    active_ids = {entry["session_id"] for entry in provider.list_active_sessions()}
    assert old_session_id in active_ids


def test_activity_change_starts_fresh_primary_session(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007002-007002"
    config_path = write_config(tmp_path / "cfg.yaml", _nested_config_yaml())
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)

    provider = StubProvider()
    initial_context = _resolved_context(config, workspace, "planner", "initial_plan")
    revision_context = _resolved_context(config, workspace, "planner", "plan_revision")
    manifest = {"phase": PLANNING, "goal": "plan"}

    provider.script_turn(done_events(text="planner start"))
    old_session_id = provider.start_primary_session(
        "planner",
        manifest,
        model=initial_context.model,
    )
    list(provider.stream_events(old_session_id))
    binding_before = get_primary_binding(store.load_run(run_id), "planner")
    _bind_primary_with_activity(
        store,
        run_id,
        role="planner",
        session_id=old_session_id,
        activity=initial_context.activity,
        context_digest=initial_context.context_digest,
    )

    provider.script_turn(done_events(text="planner revision start"))
    events: list[str] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append(event_type)

    new_session_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLANNING,
        requested=revision_context,
        manifest=manifest,
        append_event=append_event,
        resume_request={"action": "continue", "phase": PLANNING},
    )

    assert new_session_id != old_session_id
    binding_after = get_primary_binding(store.load_run(run_id), "planner")
    assert binding_after is not None
    assert binding_before is not None
    assert binding_after.generation == binding_before.generation + 1
    assert binding_after.activity == "plan_revision"
    assert binding_after.context_digest == revision_context.context_digest
    assert binding_after.provider_session_id == new_session_id
    assert "planner_session_ended" in events
    assert "planner_session_started" in events
    active_ids = {entry["session_id"] for entry in provider.list_active_sessions()}
    assert old_session_id not in active_ids
    assert new_session_id in active_ids


def test_digest_change_starts_fresh_primary_session(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007003-007003"
    config_path = write_config(
        tmp_path / "cfg.yaml",
        _nested_config_yaml(planner_initial_model="smart"),
    )
    from top_down_planning.config import resolve_config

    config = resolve_config(config_path, cwd=workspace)
    _create_run(store, run_id, config)

    altered_config_path = write_config(
        tmp_path / "cfg-altered.yaml",
        _nested_config_yaml(planner_initial_model="fast"),
    )
    altered_config = resolve_config(altered_config_path, cwd=workspace)

    provider = StubProvider()
    initial_context = _resolved_context(config, workspace, "planner", "initial_plan")
    altered_context = _resolved_context(altered_config, workspace, "planner", "initial_plan")
    assert altered_context.context_digest != initial_context.context_digest
    manifest = {"phase": PLANNING, "goal": "plan"}

    provider.script_turn(done_events(text="planner start"))
    old_session_id = provider.start_primary_session(
        "planner",
        manifest,
        model=initial_context.model,
    )
    list(provider.stream_events(old_session_id))
    binding_before = get_primary_binding(store.load_run(run_id), "planner")
    _bind_primary_with_activity(
        store,
        run_id,
        role="planner",
        session_id=old_session_id,
        activity=initial_context.activity,
        context_digest=initial_context.context_digest,
    )

    provider.script_turn(done_events(text="planner fresh start"))
    events: list[str] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append(event_type)

    new_session_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase=PLANNING,
        requested=altered_context,
        manifest=manifest,
        append_event=append_event,
        resume_request={"action": "continue", "phase": PLANNING},
    )

    assert new_session_id != old_session_id
    binding_after = get_primary_binding(store.load_run(run_id), "planner")
    assert binding_after is not None
    assert binding_before is not None
    assert binding_after.generation == binding_before.generation + 1
    assert binding_after.activity == "initial_plan"
    assert binding_after.context_digest == altered_context.context_digest
    assert binding_after.provider_session_id == new_session_id
    assert "planner_session_ended" in events
    active_ids = {entry["session_id"] for entry in provider.list_active_sessions()}
    assert old_session_id not in active_ids
    assert new_session_id in active_ids
