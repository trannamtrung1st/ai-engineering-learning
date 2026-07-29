"""Worker chat continuity within a TODO."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

import pytest

from todos_tool.orchestrator import Orchestrator
from todos_tool.persistence import load_state
from todos_tool.run_config import RunConfig
from tests.helpers import write_todos


@pytest.mark.asyncio
async def test_validation_repair_resumes_same_worker_chat(
    git_project,
    fake_agent,
    sample_item,
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
    wrapper = fake_agent.parent / "agent-validation-repair-continuity"
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
    attempt_dir = git_project / "todos/runs/TASK-001/attempts/01"
    work_sessions = sorted(attempt_dir.glob("work-session-*.ndjson"))
    assert len(work_sessions) >= 2
    session_ids: list[str] = []
    for path in work_sessions:
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("type") == "system" and event.get("subtype") == "init":
                session_ids.append(event["session_id"])
    assert session_ids
    assert session_ids[0] == session_ids[-1] == "fake-session-TASK-001-1"


@pytest.mark.asyncio
async def test_fresh_worker_chat_per_todo(git_project, fake_agent, sample_item) -> None:
    item_a = dict(sample_item)
    item_b = {
        **sample_item,
        "id": "TASK-002",
        "title": "Second task",
        "depends_on": ["TASK-001"],
        "_file": "items/002.yaml",
    }
    write_todos(git_project, [item_a, item_b], settings={"auto_commit": False})
    os.environ["FAKE_AGENT_WORKSPACE"] = str(git_project)
    os.environ["FAKE_AGENT_DECISION"] = "pass"
    config = RunConfig(
        workspace_root=git_project,
        agent_bin=str(fake_agent),
        skip_probe=True,
        auto_commit=False,
    )
    orch = Orchestrator(config)
    report = await orch.run()
    assert report.completed == ["TASK-001", "TASK-002"]

    def first_session_id(item_id: str) -> str:
        path = (
            git_project
            / "todos/runs"
            / item_id
            / "attempts/01/work-session-1.ndjson"
        )
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("type") == "system" and event.get("subtype") == "init":
                return event["session_id"]
        raise AssertionError(f"no session id in {path}")

    assert first_session_id("TASK-001") == "fake-session-TASK-001-1"
    assert first_session_id("TASK-002") == "fake-session-TASK-002-1"


@pytest.mark.asyncio
async def test_deterministic_review_skips_reviewer_session(
    git_project,
    fake_agent,
    sample_item,
) -> None:
    write_todos(
        git_project,
        [
            {
                **sample_item,
                "review_policy": "deterministic",
                "validation": {"commands": ["pytest"]},
            }
        ],
        settings={"auto_commit": False},
    )
    os.environ["FAKE_AGENT_WORKSPACE"] = str(git_project)
    os.environ["FAKE_AGENT_DECISION"] = "pass"
    config = RunConfig(
        workspace_root=git_project,
        agent_bin=str(fake_agent),
        skip_probe=True,
        auto_commit=False,
    )
    orch = Orchestrator(config)
    report = await orch.run()
    assert report.completed == ["TASK-001"]
    attempt_dir = git_project / "todos/runs/TASK-001/attempts/01"
    assert not list(attempt_dir.glob("review-session-*.ndjson"))


def test_run_state_rejects_schema_v2(tmp_path) -> None:
    from todos_tool.errors import PersistenceError

    runs_dir = tmp_path / "TASK-001"
    runs_dir.mkdir(parents=True)
    legacy = {
        "schema_version": 2,
        "item_id": "TASK-001",
        "logical_attempt": 1,
        "phase": "idle",
        "session_number": 0,
        "session_restart_count": 0,
        "review": {},
        "commit_state": "none",
        "changed_paths": [],
        "evidence_attempt": 0,
        "evidence_repair_count": 0,
        "evidence_results": [],
        "evidence_identical_failure_count": 0,
        "validation_attempt": 0,
        "validation_repair_count": 0,
        "validation_results": [],
        "history": [],
    }
    (runs_dir / "state.json").write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(PersistenceError, match="Unsupported run state schema version"):
        load_state(runs_dir)
