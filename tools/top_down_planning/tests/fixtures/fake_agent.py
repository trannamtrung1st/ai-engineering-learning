#!/usr/bin/env python3
"""Deterministic fake Cursor agent for planning integration tests."""

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


def _render_tool_env() -> dict[str, str]:
    env = _plan_tool_env()
    return env


def _run_render_tool(*args: str) -> None:
    env = _render_tool_env()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_SRC_ROOT}{os.pathsep}{existing}" if existing else str(_SRC_ROOT)
    )
    subprocess.run(
        [sys.executable, "-m", "top_down_planning.render_tool", *args],
        env=env,
        check=True,
    )


def _render_eligible_ids(prompt: str) -> list[str]:
    env_ids = os.environ.get("RENDER_TOOL_ELIGIBLE_IDS", "")
    if env_ids.strip():
        return [part.strip() for part in env_ids.split(",") if part.strip()]
    return re.findall(r"^\| (item-\d+) \|", prompt, re.MULTILINE)


def _write_render_batch_selection(prompt: str) -> None:
    if not os.environ.get("RENDER_TOOL_BATCH_FILE"):
        return
    batch_ids = _render_eligible_ids(prompt)
    if not batch_ids:
        batch_ids = re.findall(r"^### Selected item `([^`]+)`", prompt, re.MULTILINE)
    if not batch_ids:
        batch_ids = ["item-001"]
    args: list[str] = ["select-batch"]
    for node_id in batch_ids:
        args.extend(["--node-id", node_id])
    _run_render_tool(*args)


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


def _workspace_root() -> Path:
    return Path(os.environ.get("PLANNING_TOOL_WORKSPACE", os.getcwd())).resolve()


def _selected_ids(prompt: str) -> list[str]:
    env_ids = os.environ.get("PLANNING_TOOL_ELIGIBLE_IDS", "")
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
                "operations": [
                    {
                        "type": "expand",
                        "node_id": "item-001",
                        "reason": "Multiple planning areas",
                        "title": "Plan the CSV conversion CLI",
                        "objective": "Define the work required to deliver the requested CLI.",
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
        operation = {
            "type": "mark_actionable",
            "node_id": node_id,
            "reason": "Detailed enough",
            "expected_outputs": [f"Output for {node_id}"],
            "acceptance_criteria": [f"Done when {node_id} complete"],
            "dependencies": [],
        }
        if node_id == "item-001":
            operation.update(
                {
                    "title": "Plan the CSV conversion CLI",
                    "objective": "Define the work required to deliver the requested CLI.",
                }
            )
        operations.append(operation)
    return {"operations": operations}


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
    return {"operations": operations}


def _eligible_ids(prompt: str) -> list[str]:
    env_ids = os.environ.get("PLANNING_TOOL_ELIGIBLE_IDS", "")
    if env_ids.strip():
        return [part.strip() for part in env_ids.split(",") if part.strip()]
    table_ids = re.findall(r"^\| (item-\d+) \|", prompt, re.MULTILINE)
    if table_ids:
        return table_ids
    return _selected_ids(prompt)


def _write_planning_transaction(response: dict, batch_ids: list[str]) -> None:
    if not os.environ.get("PLANNING_TOOL_TXN_FILE"):
        raise RuntimeError("PLANNING_TOOL_TXN_FILE is required for planning sessions")

    if batch_ids:
        args: list[str] = ["select-batch"]
        for node_id in batch_ids:
            args.extend(["--node-id", node_id])
        _run_plan_tool(*args)

    for operation in response.get("operations") or []:
        _run_plan_tool(
            "record-operation",
            "--json",
            json.dumps(operation, separators=(",", ":")),
        )
    for update in response.get("updates") or []:
        _run_plan_tool(
            "record-update",
            "--json",
            json.dumps(update, separators=(",", ":")),
        )
    _run_plan_tool("finalize")


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


def _artifact_path() -> str:
    return os.environ.get("FAKE_AGENT_RENDER_ARTIFACT", "implementation-plan.md")


def _write_artifact(workspace: Path, relative_path: str, content: str) -> None:
    destination = workspace / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _write_scaffold_output(prompt: str) -> None:
    workspace = _workspace_root()
    path = _artifact_path()
    titles = re.findall(r"^### \d+\. (.+)$", prompt, re.MULTILINE)
    sections = "\n".join(f"## {title}\n\n_TBD_\n" for title in titles) or "## Overview\n\n_TBD_\n"
    _write_artifact(
        workspace,
        path,
        f"# Deliverable\n\nScaffold for cumulative render output.\n\n{sections}",
    )


def _write_batch_output(prompt: str) -> None:
    workspace = _workspace_root()
    path = _artifact_path()
    destination = workspace / path
    existing = destination.read_text(encoding="utf-8") if destination.is_file() else "# Deliverable\n\n"
    batch_match = re.search(r"Render batch (?:author|revision) session: batch (\d+)", prompt)
    batch_index = batch_match.group(1) if batch_match else "0"
    titles = re.findall(r"^### Selected item `([^`]+)`", prompt, re.MULTILINE)
    if not titles:
        titles = re.findall(r"^### \d+\. (.+)$", prompt, re.MULTILINE)
    additions = "\n".join(
        f"## Batch {batch_index}: {title}\n\nRendered content for batch {batch_index}.\n"
        for title in titles
    ) or f"## Batch {batch_index}\n\nRendered batch content.\n"
    _write_artifact(workspace, path, existing.rstrip() + "\n\n" + additions)


def _write_render_batch_review(prompt: str) -> None:
    digest_match = re.search(r"## Plan digest\n`([a-f0-9]+)`", prompt)
    goal_match = re.search(r"## Output-goal digest\n`([a-f0-9]+)`", prompt)
    batches_match = re.search(r"## Processed batches digest\n`([a-f0-9]+)`", prompt)
    deliverable_match = re.search(r"## Deliverable output digest\n`([a-f0-9]+)`", prompt)
    batch_match = re.search(r"Render batch review session: batch (\d+)", prompt)
    payload = {
        "stage": "render_batch_review",
        "batch_index": int(batch_match.group(1)) if batch_match else 0,
        "plan_digest": digest_match.group(1) if digest_match else "0" * 64,
        "output_goal_digest": goal_match.group(1) if goal_match else "0" * 64,
        "processed_batches_digest": batches_match.group(1) if batches_match else "0" * 64,
        "deliverable_output_digest": deliverable_match.group(1) if deliverable_match else "0" * 64,
        "decision": "approve",
        "summary": "Batch approved by fake reviewer.",
        "findings": [],
    }
    _run_review_tool(
        "set-result",
        "--json",
        json.dumps(payload, separators=(",", ":")),
    )
    _run_review_tool("finalize")


def _write_render_output_review(prompt: str) -> None:
    digest_match = re.search(r"## Plan digest\n`([a-f0-9]+)`", prompt)
    goal_match = re.search(r"## Output-goal digest\n`([a-f0-9]+)`", prompt)
    batches_match = re.search(r"## Processed batches digest\n`([a-f0-9]+)`", prompt)
    deliverable_match = re.search(r"## Deliverable output digest\n`([a-f0-9]+)`", prompt)
    payload = {
        "stage": "rendered_output_review",
        "plan_digest": digest_match.group(1) if digest_match else "0" * 64,
        "output_goal_digest": goal_match.group(1) if goal_match else "0" * 64,
        "processed_batches_digest": batches_match.group(1) if batches_match else "0" * 64,
        "deliverable_output_digest": deliverable_match.group(1) if deliverable_match else "0" * 64,
        "decision": "approve",
        "summary": "Rendered output approved by fake reviewer.",
        "findings": [],
        "affected_batch_indices": [],
        "affected_artifact_paths": [],
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

    if "Render scaffold session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-render-scaffold-session",
                "model": "fake-model",
            }
        )
        _write_scaffold_output(prompt)
        assistant("Created render scaffold.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Render batch author session" in prompt or "Render batch revision session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-render-batch-session",
                "model": "fake-model",
            }
        )
        if "Render batch author session" in prompt:
            _write_render_batch_selection(prompt)
        _write_batch_output(prompt)
        assistant("Updated cumulative render deliverables.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Render final revision session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-render-final-revision-session",
                "model": "fake-model",
            }
        )
        _write_batch_output(prompt)
        assistant("Applied final render revisions.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    if "Render batch review session" in prompt:
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "fake-render-batch-review-session",
                "model": "fake-model",
            }
        )
        _write_render_batch_review(prompt)
        assistant("Finalized render batch review.")
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
        _write_planning_transaction(_default_amend_response(selected), selected)
        assistant("Finalized amendment transaction.")
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    batch_ids = _eligible_ids(prompt)

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
        response = _default_planning_response(batch_ids)

    _write_planning_transaction(response, batch_ids)
    assistant("Finalized planning transaction.")
    emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
