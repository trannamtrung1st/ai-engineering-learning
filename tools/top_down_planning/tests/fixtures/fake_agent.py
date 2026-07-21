#!/usr/bin/env python3
"""Deterministic fake Cursor agent for planning integration tests.

Controlled by environment:

- FAKE_AGENT_MODE: planning|timeout|malformed|crash|split
- FAKE_AGENT_PLANNING_JSON: full planning response override
- FAKE_AGENT_EXPAND_ROOT=true expands item-001 once, then marks leaves actionable
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def assistant(text: str, ts: int | None = 1) -> None:
    event: dict = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    if ts is not None:
        event["timestamp_ms"] = ts
    emit(event)


def _prompt_text() -> str:
    prompt_file = os.environ.get("PLANNING_TOOL_PROMPT_FILE")
    if prompt_file and Path(prompt_file).is_file():
        return Path(prompt_file).read_text(encoding="utf-8")
    return sys.argv[-1] if len(sys.argv) > 1 else ""


def _selected_ids(prompt: str) -> list[str]:
    return re.findall(r"Selected item `([^`]+)`", prompt)


def _default_planning_response(selected: list[str]) -> dict:
    if os.environ.get("FAKE_AGENT_EXPAND_ROOT", "true").lower() in {"1", "true", "yes"}:
        if "item-001" in selected:
            return {
                "assessment": {"plan_complete": False, "summary": "Root expanded"},
                "operations": [
                    {
                        "type": "expand",
                        "node_id": "item-001",
                        "reason": "Multiple planning areas",
                        "children": [
                            {
                                "ref": "child-1",
                                "title": "Define CLI interface",
                                "objective": "Specify the command-line interface",
                                "expected_outputs": ["CLI spec"],
                                "acceptance_criteria": ["All flags documented"],
                            },
                            {
                                "ref": "child-2",
                                "title": "Implement CSV parser",
                                "objective": "Parse CSV rows safely",
                                "dependencies": ["child-1"],
                                "expected_outputs": ["Parser module"],
                                "acceptance_criteria": ["Malformed rows handled"],
                            },
                        ],
                    }
                ],
            }

    operations = []
    for node_id in selected:
        operations.append(
            {
                "type": "mark_actionable",
                "node_id": node_id,
                "reason": "Detailed enough",
                "expected_outputs": [f"Output for {node_id}"],
                "acceptance_criteria": [f"Done when {node_id} complete"],
                "dependencies": [],
            }
        )
    return {
        "assessment": {
            "plan_complete": len(operations) > 0,
            "summary": "Leaves marked actionable",
        },
        "operations": operations,
    }


def _default_render_response() -> str:
    payload = {
        "artifacts": [
            {
                "relative_path": "implementation-plan.md",
                "content": """# Actionable Implementation Plan

Rendered according to the output goal after decomposition completed.

## Hierarchical view

1. **Define CLI interface**
   - Objective: Specify the command-line interface
   - Expected outputs: CLI spec
   - Acceptance criteria: All flags documented

2. **Implement CSV parser**
   - Objective: Parse CSV rows safely
   - Expected outputs: Parser module
   - Acceptance criteria: Malformed rows handled
   - Dependencies: Define CLI interface

## Actionable items

1. **Define CLI interface**
   - Objective: Specify the command-line interface
   - Expected outputs: CLI spec
   - Acceptance criteria: All flags documented

2. **Implement CSV parser**
   - Objective: Parse CSV rows safely
   - Dependencies: Define CLI interface
   - Expected outputs: Parser module
   - Acceptance criteria: Malformed rows handled
""",
            }
        ]
    }
    return "```json\n" + json.dumps(payload, indent=2) + "\n```\n"


def main() -> int:
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        sys.stdout.write("fake planning agent\n")
        return 0

    mode = os.environ.get("FAKE_AGENT_MODE", "planning")
    prompt = _prompt_text()

    if "Final planning render" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-planning-session",
                "model": "fake-model",
            }
        )
        assistant(_default_render_response())
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    selected = _selected_ids(prompt)

    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": "fake-planning-session",
            "model": "fake-model",
        }
    )

    if mode == "timeout":
        assistant("planning...")
        time.sleep(float(os.environ.get("FAKE_AGENT_SLEEP", "60")))
        return 0

    if mode == "crash":
        assistant("about to crash")
        return 2

    if mode == "malformed":
        sys.stdout.write("not-json\n")
        sys.stdout.flush()
        assistant("malformed")
        emit({"type": "result", "subtype": "success", "duration_ms": 1, "is_error": False})
        return 0

    if mode == "split":
        payload = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}) + "\n"
        mid = len(payload) // 2
        sys.stdout.buffer.write(payload[:mid].encode("utf-8"))
        sys.stdout.buffer.flush()
        time.sleep(0.01)
        sys.stdout.buffer.write(payload[mid:].encode("utf-8"))
        sys.stdout.buffer.flush()
        emit({"type": "result", "subtype": "success", "duration_ms": 1, "is_error": False})
        return 0

    override = os.environ.get("FAKE_AGENT_PLANNING_JSON")
    if override:
        response = json.loads(override)
    else:
        response = _default_planning_response(selected)

    assistant("```json\n" + json.dumps(response, indent=2) + "\n```\n")
    emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
