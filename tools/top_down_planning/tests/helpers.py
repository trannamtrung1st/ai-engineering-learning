"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def test_run_workspace(store: Any) -> str:
    """Workspace path for test runs (required on ``create_run``)."""

    return str(store.root)


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def run_digests_for_config(
    store_root: Path,
    config: dict[str, Any],
) -> tuple[str, str]:
    from top_down_planning.config import compute_input_digest, compute_output_goal_digest

    return (
        compute_input_digest(config, base_dir=store_root),
        compute_output_goal_digest(config),
    )


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
