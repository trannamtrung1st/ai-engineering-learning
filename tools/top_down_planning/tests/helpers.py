"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence.capabilities import CAPABILITY_ENV_VAR


def test_run_workspace(store: Any) -> str:
    """Workspace path for test runs (required on ``create_run``)."""

    return str(store.root)


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def ensure_input_ref_files(workspace: Path, config: dict[str, Any]) -> None:
    """Create stub files for configured input refs when tests reference paths."""

    run_section = config.get("run")
    if not isinstance(run_section, dict):
        return

    for ref in run_section.get("input_refs") or []:
        ref_text = str(ref).strip()
        if not ref_text or any(char in ref_text for char in "*?[]"):
            continue
        target = workspace / ref_text
        if target.is_file():
            continue
        if target.is_dir():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"fixture content for {ref_text}\n", encoding="utf-8")


def minimal_resolved_config(**overrides: Any) -> dict[str, Any]:
    """Return a minimal resolved config snapshot for test runs."""

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["project"]["workspace"] = "."
    config["run"]["output_goal"] = "Goal."
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            merged = copy.deepcopy(config[key])
            merged.update(value)
            config[key] = merged
        else:
            config[key] = value
    return config


def run_digests_for_config(
    workspace: Path,
    config: dict[str, Any],
) -> tuple[str, str, str]:
    from top_down_planning.config import (
        compute_context_digest_from_config,
        compute_input_digest,
        compute_output_goal_digest,
    )

    return (
        compute_input_digest(config, base_dir=workspace),
        compute_output_goal_digest(config, base_dir=workspace),
        compute_context_digest_from_config(config, workspace=workspace),
    )


def minimal_invocation(
    workspace: Path,
    *,
    source: str = "test",
    command: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Minimal invocation metadata for test runs."""

    return {
        "observability": copy.deepcopy(DEFAULT_CONFIG["observability"]),
        "runs_dir": {"path": str(workspace.resolve()), "source": source},
        "stream_json": False,
        "until": until,
        "command": command,
    }


def create_run_kwargs(
    workspace: Path,
    *,
    resolved_config: dict[str, Any] | None = None,
) -> dict[str, str | dict[str, Any]]:
    """Return shared ``create_run`` digest/config kwargs for tests."""

    config = resolved_config or minimal_resolved_config()
    if isinstance(config.get("project"), dict):
        config = copy.deepcopy(config)
        config["project"]["workspace"] = str(workspace.resolve())
    ensure_input_ref_files(workspace, config)
    input_digest, output_goal_digest, context_digest = run_digests_for_config(
        workspace,
        config,
    )
    return {
        "resolved_config": config,
        "input_digest": input_digest,
        "output_goal_digest": output_goal_digest,
        "context_digest": context_digest,
        "workspace": str(workspace.resolve()),
        "invocation": minimal_invocation(workspace),
    }


def approved_digests_from_run(store: Any, run_id: str) -> dict[str, str]:
    from top_down_planning.persistence import FileRunStore

    if not isinstance(store, FileRunStore):
        raise TypeError("store must be a FileRunStore")
    run = store.load_run(run_id)
    return {
        str(key): str(value)
        for key, value in (run.get("digests") or {}).items()
        if value is not None
    }


def whole_plan_approval_record(store: Any, run_id: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "review-whole-plan-01",
        "type": "whole_plan",
        "reviewer_session_id": "stub-session-reviewer",
        "target_revision": 0,
        "scope": {"kind": "whole_plan"},
        "status": "approved",
        "findings": [],
        "revision_cycles": 0,
        "approved_digests": approved_digests_from_run(store, run_id),
    }
    payload.update(fields)
    return payload


def whole_output_approval_record(store: Any, run_id: str, **fields: Any) -> dict[str, Any]:
    from top_down_planning.persistence.digests import compute_output_digest

    digests = approved_digests_from_run(store, run_id)
    production = store.load_production(run_id)
    digests["output"] = compute_output_digest(production)
    payload: dict[str, Any] = {
        "id": "review-whole-output-01",
        "type": "whole_output",
        "reviewer_session_id": "stub-session-output-reviewer",
        "target_revision": int(production["output_revision"]),
        "scope": {"kind": "whole_output"},
        "status": "approved",
        "findings": [],
        "revision_cycles": 0,
        "approved_digests": digests,
    }
    payload.update(fields)
    return payload


def grant_capability(
    store: Any,
    run_id: str,
    *,
    role: str,
    phase: str | None = None,
    session_kind: str = "primary",
    session_id: str | None = None,
    loop_id: str | None = None,
) -> str:
    """Issue a session capability token and return its serialized value."""

    from top_down_planning.orchestrator.capability import issue_session_capability

    if phase is None:
        phase = PLANNING if role == "planner" else PRODUCTION

    run = store.load_run(run_id)
    sessions = dict(run.get("sessions") or {})

    if role == "planner":
        if session_id is not None:
            resolved_session_id = session_id
        else:
            resolved_session_id = sessions.get("primary_planner_session_id") or "test-planner-session"
        if sessions.get("primary_planner_session_id") is None:
            sessions["primary_planner_session_id"] = resolved_session_id
            run = dict(run)
            run["sessions"] = sessions
            expected = int(run["revision"])
            run["revision"] = expected + 1
            store.save_run(run_id, run, expected)
    elif role == "producer":
        if session_id is not None:
            resolved_session_id = session_id
        else:
            resolved_session_id = sessions.get("primary_producer_session_id") or "test-producer-session"
        if sessions.get("primary_producer_session_id") is None:
            sessions["primary_producer_session_id"] = resolved_session_id
            run = dict(run)
            run["sessions"] = sessions
            expected = int(run["revision"])
            run["revision"] = expected + 1
            store.save_run(run_id, run, expected)
    else:
        resolved_session_id = session_id or "test-reviewer-session"

    resolved_loop_id: str | None = None
    if session_kind == "reviewer" or role == "reviewer":
        resolved_loop_id = loop_id or "review-test-loop"
        try:
            loop = dict(store.load_review(run_id, resolved_loop_id))
            if loop.get("reviewer_session_id") != resolved_session_id:
                loop["reviewer_session_id"] = resolved_session_id
                store.save_review(run_id, loop)
        except Exception:
            pass

    return issue_session_capability(
        store,
        run_id,
        role=role,
        phase=phase,
        session_id=resolved_session_id,
        session_kind=session_kind,
        loop_id=resolved_loop_id,
    )


def set_capability_env(monkeypatch: Any, token: str | None) -> None:
    """Set or clear TDP_CAPABILITY_TOKEN for CLI and service tests."""

    if token is None:
        monkeypatch.delenv(CAPABILITY_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(CAPABILITY_ENV_VAR, token)


def script_reviewer_allocate(provider: Any) -> None:
    """Queue the allocation turn consumed before a new reviewer review package."""

    provider.script_turn(done_events(text="reviewer allocate"))


def done_events(*, signal: str | None = None, text: str = "ok") -> list[dict]:
    events = [
        {"type": "assistant", "text": text},
        {"type": "done", "subtype": "success", "text": text, "is_error": False},
    ]
    if signal is not None:
        events[-1]["signal"] = signal
    return events


def apply_plan(
    store: Any,
    run_id: str,
    *,
    base_revision: int,
    operations: list[dict],
    role: str = "planner",
    phase: str | None = None,
) -> Any:
    from top_down_planning.agent_tool import PlanAgentService

    resolved_phase = phase or (PLANNING if role == "planner" else PRODUCTION)

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=resolved_phase)
        PlanAgentService(store, run_id).apply(
            {"base_revision": base_revision, "operations": operations},
            capability_token=token,
        )

    return mutate


def request_focused_review(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "planner",
    phase: str = PLANNING,
) -> Any:
    from top_down_planning.agent_tool import ReviewAgentService

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=phase)
        ReviewAgentService(store, run_id).request(request, capability_token=token)

    return mutate


def respond_review(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "reviewer",
    phase: str = PLANNING,
    loop_id: str | None = None,
    session_id: str | None = None,
) -> Any:
    from top_down_planning.agent_tool import ReviewAgentService

    resolved_loop_id = loop_id or str(request.get("loop_id") or "")

    def mutate() -> None:
        resolved_session_id = session_id
        if resolved_session_id is None and resolved_loop_id:
            try:
                loop = store.load_review(run_id, resolved_loop_id)
                loop_session = loop.get("reviewer_session_id")
                if isinstance(loop_session, str) and loop_session:
                    resolved_session_id = loop_session
            except Exception:
                pass
        token = grant_capability(
            store,
            run_id,
            role=role,
            phase=phase,
            loop_id=resolved_loop_id,
            session_id=resolved_session_id,
        )
        ReviewAgentService(store, run_id).respond(request, capability_token=token)

    return mutate


def apply_production(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    handler: str,
    role: str = "producer",
    phase: str = PRODUCTION,
) -> Any:
    from top_down_planning.agent_tool import ProductionAgentService

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=phase)
        ProductionAgentService(store, run_id).__getattribute__(handler)(
            request,
            capability_token=token,
        )

    return mutate


def only_run_id(store: Any) -> str:
    """Return the sole run directory id under a test store root."""

    run_dirs = sorted(
        path.name
        for path in store.root.iterdir()
        if path.is_dir() and path.name.startswith("run-")
    )
    if len(run_dirs) != 1:
        raise AssertionError(f"expected exactly one run in store, found {run_dirs}")
    return run_dirs[0]


def request_amendment(
    store: Any,
    run_id: str,
    request: dict[str, Any],
    *,
    role: str = "producer",
    phase: str = PRODUCTION,
) -> Any:
    from top_down_planning.agent_tool import ProductionAgentService

    def mutate() -> None:
        token = grant_capability(store, run_id, role=role, phase=phase)
        ProductionAgentService(store, run_id).request_amendment(
            request,
            capability_token=token,
        )

    return mutate


def plan_apply_turn(
    *,
    base_revision: int = 0,
    operations: list[dict],
    signal: str = "candidate_plan_ready",
    assistant_text: str = "planning turn",
) -> list[dict]:
    """Return provider events for a planning turn that signals completion only."""

    del base_revision, operations
    return done_events(signal=signal, text=assistant_text)

