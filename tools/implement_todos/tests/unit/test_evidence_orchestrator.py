"""Orchestrator integration for completion-evidence gate."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.errors import TodosToolError
from todos_tool.models import EvidenceMode, ItemStatus, Transition
from todos_tool.orchestrator import Orchestrator, RunConfig
from todos_tool.persistence import load_state, new_run_state, record_transition, save_state


@pytest.mark.asyncio
async def test_evidence_failure_skips_review_session(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    item = dict(sample_item)
    item["validation"] = {"commands": []}
    item["evidence"] = {
        "commands": [{"command": "pytest tests/unit/test_missing.py"}],
    }
    write_todos(
        git_project,
        [item],
        settings={
            "max_attempts": 1,
            "max_validation_repairs_per_attempt": 0,
            "auto_commit": False,
            "project_check": f"{shlex.quote(sys.executable)} -c 'import sys; sys.exit(0)'",
        },
    )
    wrapper = fake_agent.parent / "agent-evidence-skip-review"
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
            evidence_mode="captured",
            max_identical_evidence_failures=1,
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.blocked == ["TASK-001"]
    attempt_dir = git_project / "todos" / "runs" / "TASK-001" / "attempts" / "01"
    assert not list(attempt_dir.glob("review-session-*.ndjson"))
    evidence = json.loads((attempt_dir / "evidence-results.json").read_text(encoding="utf-8"))
    assert evidence["passed"] is False


@pytest.mark.asyncio
async def test_driver_mode_runs_evidence_and_review(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    item = dict(sample_item)
    item["validation"] = {"commands": []}
    item["evidence"] = {"commands": [{"command": "echo evidence-ok"}]}
    project_check = f"{shlex.quote(sys.executable)} -c 'import sys; sys.exit(0)'"
    write_todos(
        git_project,
        [item],
        settings={
            "max_attempts": 1,
            "max_validation_repairs_per_attempt": 0,
            "auto_commit": False,
            "project_check": project_check,
        },
    )
    evidence_json = json.dumps(
        [
            {
                "command": "echo evidence-ok",
                "cwd": ".",
                "passed": True,
                "exit_code": 0,
                "summary": "ok",
            }
        ]
    )
    validation_json = json.dumps(
        [
            {
                "command": project_check,
                "passed": True,
                "exit_code": 0,
                "summary": "ok",
            }
        ]
    )
    wrapper = fake_agent.parent / "agent-evidence-driver"
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
        f"env['FAKE_AGENT_EVIDENCE_JSON'] = {evidence_json!r}\n"
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
            evidence_mode="driver",
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.completed == ["TASK-001"]
    attempt_dir = git_project / "todos" / "runs" / "TASK-001" / "attempts" / "01"
    assert list(attempt_dir.glob("review-session-*.ndjson"))
    evidence = json.loads((attempt_dir / "evidence-results.json").read_text(encoding="utf-8"))
    assert evidence["passed"] is True
    assert evidence["mode"] == "driver"


@pytest.mark.asyncio
async def test_captured_mode_accepts_declared_shell_evidence(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    item = dict(sample_item)
    item["validation"] = {"commands": []}
    item["evidence"] = {"commands": [{"command": "echo captured-ok"}]}
    project_check = f"{shlex.quote(sys.executable)} -c 'import sys; sys.exit(0)'"
    write_todos(
        git_project,
        [item],
        settings={
            "max_attempts": 1,
            "max_validation_repairs_per_attempt": 0,
            "auto_commit": False,
            "project_check": project_check,
        },
    )
    shell_evidence = json.dumps(
        [{"command": "echo captured-ok", "cwd": ".", "exit_code": 0}]
    )
    evidence_json = json.dumps(
        [
            {
                "command": "echo captured-ok",
                "cwd": ".",
                "passed": True,
                "exit_code": 0,
                "summary": "ok",
            }
        ]
    )
    validation_json = json.dumps(
        [
            {
                "command": project_check,
                "passed": True,
                "exit_code": 0,
                "summary": "ok",
            }
        ]
    )
    wrapper = fake_agent.parent / "agent-evidence-captured"
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
        f"env['FAKE_AGENT_SHELL_EVIDENCE'] = {shell_evidence!r}\n"
        f"env['FAKE_AGENT_EVIDENCE_JSON'] = {evidence_json!r}\n"
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
            evidence_mode="captured",
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.completed == ["TASK-001"]


@pytest.mark.asyncio
async def test_resume_rejects_mismatched_evidence_mode(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item], settings={"auto_commit": False})
    from todos_tool.manifest import load_workspace, save_item
    from todos_tool.models import Phase

    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)
    runs_dir = ws.runs_dir(item.id)
    state = new_run_state(item.id, None)
    state.logical_attempt = 1
    state.phase = Phase.WORK
    state.evidence_mode = EvidenceMode.CAPTURED
    record_transition(runs_dir, state, Transition.WORK_PHASE_READY)
    save_state(runs_dir, state)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            evidence_mode="driver",
        )
    )
    report = await orch.resume()
    assert report.errors.get("TASK-001", "").startswith("Evidence mode mismatch")
