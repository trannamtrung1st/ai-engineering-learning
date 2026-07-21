"""Validation gate and repair loop tests."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.manifest import load_workspace
from todos_tool.models import ItemStatus, Phase, Transition, ValidationCommandResult
from todos_tool.orchestrator import Orchestrator, RunConfig
from todos_tool.persistence import load_state, new_run_state, record_transition
from todos_tool.prompts import build_review_prompt, build_work_prompt


def test_work_prompt_discourages_full_authoritative_check() -> None:
    from todos_tool.models import ItemType, TodoItem

    item = TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
        validation={"commands": ["pytest"]},
    )
    prompt = build_work_prompt(
        item,
        logical_attempt=1,
        resolved_commands=["bash scripts/check"],
    )
    assert "Do NOT run the full authoritative check suite" in prompt
    assert "targeted local checks" in prompt


def test_work_prompt_includes_validation_failure_feedback() -> None:
    from todos_tool.models import ItemType, TodoItem

    item = TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
    )
    prompt = build_work_prompt(
        item,
        logical_attempt=1,
        resolved_commands=["pytest"],
        validation_failure_feedback="$ pytest\npassed=false exit_code=1\nfailed",
    )
    assert "Authoritative validation failure" in prompt


def test_review_prompt_forbids_rerunning_validation() -> None:
    from todos_tool.models import ItemType, TodoItem

    item = TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
    )
    prompt = build_review_prompt(
        item,
        logical_attempt=1,
        work_summary="done",
        git_diff="",
        git_status="",
        authoritative_validation=[
            ValidationCommandResult(
                command="pytest",
                passed=True,
                exit_code=0,
                summary="ok",
            )
        ],
        resolved_commands=["pytest"],
    )
    assert "Do NOT rerun validation commands" in prompt


@pytest.mark.asyncio
async def test_validation_failure_skips_review_session(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    command = (
        f"{shlex.quote(sys.executable)} "
        "-c 'import sys; sys.exit(3)'"
    )
    item = dict(sample_item)
    item["validation"] = {"commands": []}
    write_todos(
        git_project,
        [item],
        settings={
            "max_attempts": 1,
            "max_validation_repairs_per_attempt": 0,
            "auto_commit": False,
            "project_check": command,
        },
    )
    wrapper = fake_agent.parent / "agent-validation-skip-review"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_ATTEMPT=1\n"
        "export FAKE_AGENT_WRITE_FILE=src/result.py\n"
        "export FAKE_AGENT_DECISION=pass\n"
        f"exec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin=str(wrapper),
            skip_probe=True,
            no_color=True,
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.blocked == ["TASK-001"]
    attempt_dir = (
        git_project / "todos" / "runs" / "TASK-001" / "attempts" / "01"
    )
    assert not list(attempt_dir.glob("review-session-*.ndjson"))
    validation = json.loads(
        (attempt_dir / "validation-results.json").read_text(encoding="utf-8")
    )
    assert validation["results"][0]["passed"] is False


@pytest.mark.asyncio
async def test_validation_repair_can_pass_within_one_attempt(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    counter = git_project / ".validation-attempts"
    command = (
        f"{shlex.quote(sys.executable)} "
        f"-c \"import pathlib, sys; p=pathlib.Path({str(counter)!r}); "
        "n=int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n+1)); sys.exit(0 if n >= 1 else 1)\""
    )
    item = dict(sample_item)
    item["validation"] = {"commands": []}
    write_todos(
        git_project,
        [item],
        settings={
            "max_attempts": 1,
            "max_validation_repairs_per_attempt": 2,
            "auto_commit": False,
            "project_check": command,
        },
    )
    wrapper = fake_agent.parent / "agent-validation-repair"
    validation_json = json.dumps(
        [
            {
                "command": command,
                "passed": True,
                "exit_code": 0,
                "summary": "ok",
            }
        ]
    )
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "env['FAKE_AGENT_ITEM_ID'] = 'TASK-001'\n"
        "env['FAKE_AGENT_ATTEMPT'] = '1'\n"
        "env['FAKE_AGENT_DECISION'] = 'pass'\n"
        f"env['FAKE_AGENT_VALIDATION_JSON'] = {validation_json!r}\n"
        "raise SystemExit(subprocess.call([sys.executable, agent, *sys.argv[1:]], env=env))\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin=str(wrapper),
            skip_probe=True,
            no_color=True,
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.completed == ["TASK-001"]
    attempt_dir = (
        git_project / "todos" / "runs" / "TASK-001" / "attempts" / "01"
    )
    assert list(attempt_dir.glob("review-session-*.ndjson"))
    assert list(attempt_dir.glob("work-session-*.ndjson"))
    assert counter.read_text(encoding="utf-8") == "2"


@pytest.mark.asyncio
async def test_resume_after_validation_failed_enters_repair(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    command = "pytest"
    item = dict(sample_item)
    item["validation"] = {"commands": [command]}
    write_todos(
        git_project,
        [item],
        settings={
            "max_attempts": 1,
            "max_validation_repairs_per_attempt": 1,
            "auto_commit": False,
        },
    )
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    from todos_tool.manifest import save_item

    save_item(ws, item)
    runs_dir = ws.runs_dir(item.id)
    state = new_run_state(
        item.id,
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=git_project, text=True
        ).strip(),
    )
    state.logical_attempt = 1
    state.phase = Phase.WORK
    state.work_summary = "work complete"
    state.validation_attempt = 1
    state.validation_results = [
        ValidationCommandResult(
            command=command,
            passed=False,
            exit_code=1,
            summary="failed",
        )
    ]
    record_transition(runs_dir, state, Transition.VALIDATION_FAILED)

    wrapper = fake_agent.parent / "agent-validation-resume-repair"
    validation_json = json.dumps(
        [
            {
                "command": command,
                "passed": True,
                "exit_code": 0,
                "summary": "ok",
            }
        ]
    )
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "env['FAKE_AGENT_ITEM_ID'] = 'TASK-001'\n"
        "env['FAKE_AGENT_ATTEMPT'] = '1'\n"
        "env['FAKE_AGENT_DECISION'] = 'pass'\n"
        "env['FAKE_AGENT_WRITE_FILE'] = 'src/fixed.py'\n"
        f"env['FAKE_AGENT_VALIDATION_JSON'] = {validation_json!r}\n"
        "raise SystemExit(subprocess.call([sys.executable, agent, *sys.argv[1:]], env=env))\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin=str(wrapper),
            skip_probe=True,
            no_color=True,
        )
    )
    report = await orch.resume()
    assert report.completed == ["TASK-001"]
    saved = load_state(runs_dir)
    assert saved is not None
    assert saved.last_transition == Transition.ITEM_DONE or saved.phase == Phase.IDLE
