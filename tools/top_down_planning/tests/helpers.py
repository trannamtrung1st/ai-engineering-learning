"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG


def test_run_workspace(store: Any) -> str:
    """Workspace path for test runs (required on ``create_run``)."""

    return str(store.root)


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


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


def done_events(*, signal: str | None = None, text: str = "ok") -> list[dict]:
    events = [
        {"type": "assistant", "text": text},
        {"type": "done", "subtype": "success", "text": text, "is_error": False},
    ]
    if signal is not None:
        events[-1]["signal"] = signal
    return events


def plan_apply_turn(
    *,
    base_revision: int = 0,
    operations: list[dict],
    signal: str = "candidate_plan_ready",
    assistant_text: str = "planning turn",
) -> list[dict]:
    return [
        {
            "type": "tool_call",
            "tool": "plan_apply",
            "role": "planner",
            "request": {
                "base_revision": base_revision,
                "operations": operations,
            },
        },
        *done_events(signal=signal, text=assistant_text),
    ]
