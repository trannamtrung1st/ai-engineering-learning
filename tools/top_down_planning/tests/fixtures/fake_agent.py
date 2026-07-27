#!/usr/bin/env python3
"""Deterministic fake Cursor agent for planning integration tests.

Controlled by environment:

- FAKE_AGENT_MODE: planning|timeout|malformed|crash|split
- FAKE_AGENT_PLANNING_JSON: full planning response override
- FAKE_AGENT_EXPAND_ROOT=true expands item-001 once, then marks leaves actionable
- PLANNING_TOOL_TXN_FILE / PLANNING_TOOL_SELECTED_IDS / PLANNING_TOOL_PLAN_FILE:
  session scope for the planning transaction CLI
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from top_down_planning.plan_tool import plan_tool_argv, resolve_plan_tool_command
from top_down_planning.render_tool import (
    ENV_CONTEXT_DIGEST,
    ENV_NODE_ID,
    ENV_STAGING_DIR,
    render_tool_argv,
    resolve_render_tool_command,
)


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
    env_ids = os.environ.get("PLANNING_TOOL_SELECTED_IDS", "")
    if env_ids.strip():
        return [part.strip() for part in env_ids.split(",") if part.strip()]
    return re.findall(r"Selected item `([^`]+)`", prompt)


def _plan_tool_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_SRC_ROOT}{os.pathsep}{existing}" if existing else str(_SRC_ROOT)
    )
    return env


def _run_plan_tool(*args: str) -> None:
    command = resolve_plan_tool_command()
    subprocess.run(
        plan_tool_argv(command, *args),
        env=_plan_tool_env(),
        check=True,
    )


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


def _default_amend_response(selected: list[str]) -> dict:
    operations = []
    for node_id in selected:
        operations.append(
            {
                "type": "revise_actionable",
                "node_id": node_id,
                "reason": "Applied review finding",
                "expected_outputs": [f"Revised output for {node_id}"],
                "acceptance_criteria": [f"Revised done when {node_id} complete"],
                "dependencies": [],
            }
        )
    return {
        "assessment": {
            "plan_complete": True,
            "summary": "Amendments applied",
        },
        "operations": operations,
    }


def _write_planning_transaction(response: dict) -> None:
    if not os.environ.get("PLANNING_TOOL_TXN_FILE"):
        raise RuntimeError("PLANNING_TOOL_TXN_FILE is required for planning sessions")

    for operation in response.get("operations") or []:
        _run_plan_tool(
            "record-operation",
            "--json",
            json.dumps(operation, separators=(",", ":")),
        )
    assessment = response.get("assessment") or {}
    plan_complete = bool(assessment.get("plan_complete", False))
    summary = str(assessment.get("summary") or "")
    assessment_args = ["set-assessment", "--summary", summary]
    if plan_complete:
        assessment_args.append("--plan-complete")
    else:
        assessment_args.append("--no-plan-complete")
    _run_plan_tool(*assessment_args)
    _run_plan_tool("finalize")


def _breakdown_titles(prompt: str) -> list[str]:
    titles = re.findall(r"^### \d+\. (.+)$", prompt, re.MULTILINE)
    if titles:
        return titles
    return [
        "Define CLI interface",
        "Implement CSV parser",
    ]


def _write_review_result(stage: str, prompt: str) -> None:
    result_file = os.environ.get("PLANNING_REVIEW_RESULT_FILE")
    if not result_file:
        raise RuntimeError("PLANNING_REVIEW_RESULT_FILE is required for review sessions")

    digest_match = re.search(r"## Plan digest\n`([a-f0-9]+)`", prompt)
    plan_digest = digest_match.group(1) if digest_match else "0" * 64

    if stage == "whole_plan_review":
        sequence_raw = os.environ.get("FAKE_AGENT_REVIEW_SEQUENCE")
        if sequence_raw:
            sequence = json.loads(sequence_raw)
            if not isinstance(sequence, list) or not sequence:
                raise RuntimeError("FAKE_AGENT_REVIEW_SEQUENCE must be a non-empty JSON array")
            index = int(os.environ.get("PLANNING_REVIEW_PASS", "0"))
            payload = sequence[min(index, len(sequence) - 1)]
        else:
            override = os.environ.get("FAKE_AGENT_REVIEW_JSON")
            if override:
                payload = json.loads(override)
            else:
                payload = {
                    "stage": "whole_plan_review",
                    "plan_digest": plan_digest,
                    "decision": "approve",
                    "summary": "Plan approved by fake reviewer.",
                    "findings": [],
                }
    else:
        override = os.environ.get("FAKE_AGENT_CONFIRMATION_JSON")
        if override:
            payload = json.loads(override)
        else:
            payload = {
                "stage": "final_confirmation",
                "plan_digest": plan_digest,
                "decision": "confirmed",
                "summary": "Plan confirmed by fake confirmer.",
                "findings": [],
            }

    payload.setdefault("stage", stage)
    if digest_match:
        payload["plan_digest"] = digest_match.group(1)
    else:
        payload.setdefault("plan_digest", plan_digest)
    _run_review_tool(
        "set-result",
        "--json",
        json.dumps(payload, separators=(",", ":")),
    )
    _run_review_tool("finalize")


def _run_review_tool(*args: str) -> None:
    command = os.environ.get("PLANNING_REVIEW_TOOL_COMMAND", "planning-review-tool")
    if " " in command.strip():
        argv = shlex.split(command) + list(args)
    else:
        argv = [command, *args]
    subprocess.run(argv, env=_plan_tool_env(), check=True)


def _run_render_tool(*args: str) -> None:
    command = resolve_render_tool_command()
    subprocess.run(
        render_tool_argv(command, *args),
        env=_plan_tool_env(),
        check=True,
    )


def _default_produce_node_id() -> str:
    return os.environ.get("FAKE_AGENT_RENDER_PRODUCE_NODE", "item-002")


def _write_render_node_transaction(prompt: str) -> None:
    match = re.search(r"# Render node session: (\S+)", prompt)
    node_id = os.environ.get(ENV_NODE_ID) or (match.group(1) if match else "item-001")
    context_digest = os.environ.get(ENV_CONTEXT_DIGEST, "ctx")
    staging_dir = Path(os.environ[ENV_STAGING_DIR])
    staging_dir.mkdir(parents=True, exist_ok=True)

    _run_render_tool(
        "begin",
        "--node-id",
        node_id,
        "--context-digest",
        context_digest,
    )

    produce_node = _default_produce_node_id()
    if node_id == produce_node and "implementation plan" in prompt.lower():
        path = "implementation-plan.md"
        artifact_key = f"artifact-{node_id}"
        content_file = staging_dir / "deliverable.md"
        content_file.write_text(_final_artifact_content(path), encoding="utf-8")
        intent = {
            "artifact_key": artifact_key,
            "path": path,
            "location": "final",
            "operation": "create",
            "owner_kind": "node",
            "owner_id": node_id,
        }
        _run_render_tool(
            "declare-artifact",
            "--json",
            json.dumps(intent, separators=(",", ":")),
        )
        _run_render_tool(
            "stage-artifact",
            "--artifact-key",
            artifact_key,
            "--content-file",
            str(content_file),
        )
        _run_render_tool("record-decision", "--decision", "produce")
    else:
        _run_render_tool(
            "record-decision",
            "--decision",
            "skip",
            "--reason",
            "Covered by primary deliverable node",
        )
    _run_render_tool("submit")


def _final_artifact_content(relative_path: str) -> str:
    if relative_path.endswith(".md"):
        return f"# Deliverable\n\nRendered content for `{relative_path}`.\n"
    if relative_path.endswith((".yaml", ".yml")):
        return f"id: rendered\ntitle: {relative_path}\n"
    return f"Rendered content for {relative_path}.\n"


def _write_render_output_review(prompt: str) -> None:
    digest_match = re.search(r"## Plan digest\n`([a-f0-9]+)`", prompt)
    goal_match = re.search(r"## Output-goal digest\n`([a-f0-9]+)`", prompt)
    manifest_match = re.search(r"## Render manifest digest\n`([a-f0-9]+)`", prompt)
    deliverable_match = re.search(r"## Deliverable output digest\n`([a-f0-9]+)`", prompt)
    payload = {
        "stage": "rendered_output_review",
        "plan_digest": digest_match.group(1) if digest_match else "0" * 64,
        "output_goal_digest": goal_match.group(1) if goal_match else "0" * 64,
        "render_manifest_digest": manifest_match.group(1) if manifest_match else "0" * 64,
        "deliverable_output_digest": deliverable_match.group(1) if deliverable_match else "0" * 64,
        "decision": "approve",
        "summary": "Rendered output approved by fake reviewer.",
        "findings": [],
        "affected_node_ids": [],
    }
    _run_review_tool(
        "set-result",
        "--json",
        json.dumps(payload, separators=(",", ":")),
    )
    _run_review_tool("finalize")


def main() -> int:
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        sys.stdout.write("fake planning agent\n")
        return 0

    mode = os.environ.get("FAKE_AGENT_MODE", "planning")
    prompt = _prompt_text()

    if "Render node session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-render-node-session",
                "model": "fake-model",
            }
        )
        _write_render_node_transaction(prompt)
        assistant("Submitted render node transaction.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Rendered output review session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-render-review-session",
                "model": "fake-model",
            }
        )
        _write_render_output_review(prompt)
        assistant("Finalized rendered output review.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Whole-plan review session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-review-session",
                "model": "fake-model",
            }
        )
        _write_review_result("whole_plan_review", prompt)
        assistant("Finalized whole-plan review result.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Final confirmation session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-confirmation-session",
                "model": "fake-model",
            }
        )
        _write_review_result("final_confirmation", prompt)
        assistant("Finalized final confirmation result.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Plan amendment session" in prompt:
        selected = _selected_ids(prompt)
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-amend-session",
                "model": "fake-model",
            }
        )
        _write_planning_transaction(_default_amend_response(selected))
        assistant("Finalized amendment transaction.")
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

    _write_planning_transaction(response)
    assistant("Finalized planning transaction.")
    emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
