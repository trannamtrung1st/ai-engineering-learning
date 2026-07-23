#!/usr/bin/env python3
"""Deterministic fake Cursor agent for integration tests.

Controlled by argv and environment:

- ``--mode ask`` still selects review behavior in the fake agent when present; otherwise review is detected from the prompt file title/content
- FAKE_AGENT_MODE overrides: work|review|timeout|crash|malformed|split|unknown
- FAKE_AGENT_DECISION=pass|fail|blocked
- FAKE_AGENT_ITEM_ID / FAKE_AGENT_ATTEMPT
- FAKE_AGENT_WRITE_FILE / FAKE_AGENT_WRITE_CONTENT
- FAKE_AGENT_REVIEW_JSON full decision override
- FAKE_AGENT_CRITERIA JSON list of criterion strings
- FAKE_AGENT_SKIP_SUBMIT=1 to finish review without writing an artifact
- FAKE_AGENT_EMIT_CHAT_JSON=1 to emit fenced JSON in chat (ignored by orchestrator)
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
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


def detect_mode(argv: list[str]) -> str:
    override = os.environ.get("FAKE_AGENT_MODE")
    if override:
        return override
    if "--mode" in argv:
        idx = argv.index("--mode")
        if idx + 1 < len(argv) and argv[idx + 1] == "ask":
            return "review"
    prompt_file = os.environ.get("TODOS_TOOL_PROMPT_FILE")
    if prompt_file and Path(prompt_file).is_file():
        text = Path(prompt_file).read_text(encoding="utf-8")
        if "Independent review session" in text:
            return "review"
    return "work"


def _resolve_prompt_text(argv: list[str]) -> str:
    prompt_file = os.environ.get("TODOS_TOOL_PROMPT_FILE")
    if prompt_file and Path(prompt_file).is_file():
        return Path(prompt_file).read_text(encoding="utf-8")
    return argv[-1] if argv else ""


def _extract_item_id(prompt_text: str) -> str | None:
    marker = "## Item `"
    if marker not in prompt_text:
        return None
    start = prompt_text.index(marker) + len(marker)
    end = prompt_text.find("`", start)
    if end < 0:
        return None
    return prompt_text[start:end]


def _submit_review_decision(review: dict) -> None:
    if os.environ.get("FAKE_AGENT_SKIP_SUBMIT"):
        return
    command = os.environ.get(
        "TODOS_TOOL_REVIEW_TOOL_COMMAND",
        f"{sys.executable} -m todos_tool.review_tool",
    ).strip()
    argv = shlex.split(command) if " " in command else [command]
    payload = json.dumps(review)
    subprocess.run(
        [*argv, "submit", "--json", payload],
        check=True,
        env=os.environ,
    )


def main() -> int:
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        sys.stdout.write(
            "Usage: fake-agent [options] [prompt]\n"
            "  --output-format stream-json\n"
            "  --stream-partial-output\n"
            "  --mode ask\n"
        )
        return 0
    if "--version" in argv or "-v" in argv:
        sys.stdout.write("fake-agent 0.0.0\n")
        return 0
    mode = detect_mode(argv)
    decision = os.environ.get("FAKE_AGENT_DECISION", "pass")
    prompt_text = _resolve_prompt_text(argv)
    item_id = os.environ.get("FAKE_AGENT_ITEM_ID") or _extract_item_id(prompt_text) or "TASK-001"
    attempt = int(os.environ.get("FAKE_AGENT_ATTEMPT", "1"))
    workspace = Path(os.environ.get("FAKE_AGENT_WORKSPACE", os.getcwd()))

    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": "fake-session",
            "model": "fake-model",
            "cwd": str(workspace),
        }
    )

    if mode == "timeout":
        assistant("working...")
        time.sleep(float(os.environ.get("FAKE_AGENT_SLEEP", "60")))
        return 0

    if mode == "crash":
        assistant("about to crash")
        return 2

    if mode == "malformed":
        for _ in range(int(os.environ.get("FAKE_AGENT_MALFORMED_COUNT", "3"))):
            sys.stdout.write("@@@\n")
            sys.stdout.flush()
        assistant("done with malformed noise")
        emit({"type": "result", "subtype": "success", "duration_ms": 1, "is_error": False})
        return 0

    if mode == "split":
        payload = (
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp_ms": 1,
                    "message": {"content": [{"type": "text", "text": "split-ok"}]},
                }
            )
            + "\n"
        )
        mid = len(payload) // 2
        sys.stdout.buffer.write(payload[:mid].encode("utf-8"))
        sys.stdout.buffer.flush()
        time.sleep(0.01)
        sys.stdout.buffer.write(payload[mid:].encode("utf-8"))
        sys.stdout.buffer.flush()
        emit({"type": "result", "subtype": "success", "duration_ms": 1, "is_error": False})
        return 0

    if mode == "unknown":
        emit({"type": "custom_mystery", "payload": {"x": 1}})
        assistant("saw unknown")
        emit({"type": "result", "subtype": "success", "duration_ms": 1, "is_error": False})
        return 0

    if mode == "work":
        shell_evidence_raw = os.environ.get("FAKE_AGENT_SHELL_EVIDENCE")
        if shell_evidence_raw:
            for entry in json.loads(shell_evidence_raw):
                command = entry["command"]
                cwd = entry.get("cwd", ".")
                emit(
                    {
                        "type": "tool_call",
                        "subtype": "started",
                        "tool_call": {
                            "shellToolCall": {
                                "args": {
                                    "command": command,
                                    "workingDirectory": cwd,
                                }
                            }
                        },
                    }
                )
                emit(
                    {
                        "type": "tool_call",
                        "subtype": "completed",
                        "tool_call": {
                            "shellToolCall": {
                                "args": {
                                    "command": command,
                                    "workingDirectory": cwd,
                                },
                                "result": {
                                    "success": {
                                        "exitCode": int(entry.get("exit_code", 0)),
                                    }
                                },
                            }
                        },
                    }
                )
        emit(
            {
                "type": "tool_call",
                "subtype": "started",
                "tool_call": {"shellToolCall": {"args": {"command": "echo hi"}}},
            }
        )
        write_rel = os.environ.get("FAKE_AGENT_WRITE_FILE")
        if write_rel:
            path = workspace / write_rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                os.environ.get("FAKE_AGENT_WRITE_CONTENT", "hello\n"),
                encoding="utf-8",
            )
        emit(
            {
                "type": "tool_call",
                "subtype": "completed",
                "tool_call": {"shellToolCall": {"args": {"command": "echo hi"}}},
            }
        )
        assistant(
            f"Implemented {item_id} on attempt {attempt}. Validation ok.\n"
            "Summary: fake work complete."
        )
        emit({"type": "result", "subtype": "success", "duration_ms": 10, "is_error": False})
        return 0

    if mode == "review":
        criteria_raw = os.environ.get("FAKE_AGENT_CRITERIA")
        if criteria_raw:
            criteria = json.loads(criteria_raw)
        else:
            criteria = [
                "A greeting helper function exists and returns a non-empty string.",
                "Basic unit tests cover the happy path.",
            ]
        validation_override = os.environ.get("FAKE_AGENT_VALIDATION_JSON")
        validation = (
            json.loads(validation_override)
            if validation_override
            else [
                {
                    "command": "pytest",
                    "passed": decision == "pass",
                    "exit_code": 0 if decision == "pass" else 1,
                    "summary": "fake",
                }
            ]
        )
        evidence_override = os.environ.get("FAKE_AGENT_EVIDENCE_JSON")
        evidence = json.loads(evidence_override) if evidence_override else []
        review = {
            "schema_version": 1,
            "item_id": item_id,
            "logical_attempt": attempt,
            "decision": decision,
            "summary": f"Review {decision} for {item_id}",
            "acceptance_criteria": [
                {
                    "criterion": c,
                    "passed": decision == "pass",
                    "evidence": "checked",
                }
                for c in criteria
            ],
            "validation": validation,
            "evidence": evidence,
            "instruction_compliance": {
                "passed": decision == "pass",
                "violations": [],
            },
            "issues": [] if decision == "pass" else ["needs work"],
            "recommended_next_action": {
                "pass": "mark_done",
                "fail": "retry",
                "blocked": "block",
            }[decision],
        }
        if decision == "pass":
            review["proposed_commit_message"] = os.environ.get(
                "FAKE_AGENT_COMMIT_MESSAGE",
                "agent: feat: implement reviewed change",
            )
        override = os.environ.get("FAKE_AGENT_REVIEW_JSON")
        if override:
            review = json.loads(override)
        if os.environ.get("FAKE_AGENT_EMIT_CHAT_JSON"):
            assistant("```json\n" + json.dumps(review, indent=2) + "\n```\n")
        if os.environ.get("FAKE_AGENT_SKIP_SUBMIT"):
            assistant("Review finished without submitting an artifact.\n")
        else:
            try:
                _submit_review_decision(review)
                assistant("Review decision submitted via todos-review-tool.\n")
            except subprocess.CalledProcessError:
                assistant("Review submission failed.\n")
                emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
                return 0
        emit({"type": "result", "subtype": "success", "duration_ms": 5, "is_error": False})
        return 0

    assistant(f"unknown mode {mode}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
