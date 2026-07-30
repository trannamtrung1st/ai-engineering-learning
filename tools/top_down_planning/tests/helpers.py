"""Shared helpers for top_down_planning tests."""

from __future__ import annotations

from pathlib import Path


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


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
