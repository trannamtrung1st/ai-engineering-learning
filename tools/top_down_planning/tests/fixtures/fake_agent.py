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


def _deliverable_dir_from_prompt(prompt: str) -> Path | None:
    match = re.search(
        r"## Deliverable directory[\s\S]*?Absolute: `([^`]+)`",
        prompt,
    )
    if match:
        return Path(match.group(1))
    return _workspace_from_prompt(prompt)


def _workspace_from_prompt(prompt: str) -> Path | None:
    match = re.search(r"## Workspace[\s\S]*?Absolute: `([^`]+)`", prompt)
    if not match:
        return None
    return Path(match.group(1))


def _breakdown_titles(prompt: str) -> list[str]:
    titles = re.findall(r"^### \d+\. (.+)$", prompt, re.MULTILINE)
    if titles:
        return titles
    return [
        "Define CLI interface",
        "Implement CSV parser",
    ]


def _default_render_content(titles: list[str]) -> str:
    lines = [
        "# Actionable Implementation Plan",
        "",
        "Rendered according to the output goal after decomposition completed.",
        "",
        "## Actionable items",
        "",
    ]
    for index, title in enumerate(titles, start=1):
        lines.extend(
            [
                f"{index}. **{title}**",
                f"   - Objective: Deliverable for {title}",
                f"   - Expected outputs: Output for {title}",
                f"   - Acceptance criteria: Done when {title} is complete",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_default_render_artifact(prompt: str) -> None:
    target_dir = _deliverable_dir_from_prompt(prompt)
    if target_dir is None:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    titles = _breakdown_titles(prompt)
    target = target_dir / "implementation-plan.md"
    target.write_text(_default_render_content(titles), encoding="utf-8")


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
        _write_default_render_artifact(prompt)
        assistant("Wrote deliverables to the workspace.")
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
