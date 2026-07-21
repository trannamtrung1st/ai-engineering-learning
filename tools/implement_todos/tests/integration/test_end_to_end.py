"""Integration tests using the fake Cursor agent."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from tests.helpers import write_todos
from todos_tool.cursor_client import CursorClient
from todos_tool.errors import CursorSessionError
from todos_tool.manifest import load_workspace
from todos_tool.models import ItemStatus
from todos_tool.orchestrator import Orchestrator, RunConfig


@pytest.mark.asyncio
async def test_stream_split_and_unknown(fake_agent: Path, git_project: Path) -> None:
    env = os.environ.copy()
    env["FAKE_AGENT_MODE"] = "split"
    # Run via CursorClient with env — monkeypatch by wrapping binary
    wrapper = fake_agent.parent / "agent-wrap"
    wrapper.write_text(
        f"#!/bin/sh\nexport FAKE_AGENT_MODE=split\nexec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    result = await client.run_session(
        workspace=git_project,
        prompt="hi",
        phase="work",
        timeout_seconds=10,
    )
    assert "split-ok" in result.assistant_text

    wrapper.write_text(
        f"#!/bin/sh\nexport FAKE_AGENT_MODE=unknown\nexec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    result = await client.run_session(
        workspace=git_project,
        prompt="hi",
        phase="work",
        timeout_seconds=10,
    )
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_parse_error_threshold(fake_agent: Path, git_project: Path) -> None:
    wrapper = fake_agent.parent / "agent-malformed"
    wrapper.write_text(
        "#!/bin/sh\n"
        "export FAKE_AGENT_MODE=malformed\n"
        "export FAKE_AGENT_MALFORMED_COUNT=5\n"
        f"exec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    client = CursorClient(
        agent_bin=str(wrapper),
        skip_probe=True,
        no_color=True,
        parse_error_threshold=3,
    )
    with pytest.raises(CursorSessionError):
        await client.run_session(
            workspace=git_project,
            prompt="hi",
            phase="work",
            timeout_seconds=10,
        )


@pytest.mark.asyncio
async def test_full_run_pass_and_commit(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={
            "max_attempts": 3,
            "max_session_restarts_per_phase": 2,
            "work_timeout_seconds": 30,
            "review_timeout_seconds": 30,
            "auto_commit": True,
            "stop_on_failure": True,
            "parse_error_threshold": 20,
        },
    )
    wrapper = fake_agent.parent / "agent-e2e"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_ATTEMPT=1\n"
        "export FAKE_AGENT_WRITE_FILE=src/greeting.py\n"
        "export FAKE_AGENT_WRITE_CONTENT='def greet(name): return f\"hi {name}\"\\n'\n"
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
            allow_dirty=False,
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.completed == ["TASK-001"]

    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.DONE
    assert item.result.commit_sha

    # Exactly one new commit beyond initial
    import subprocess

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=git_project,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "feat:" in log.stdout
    assert (git_project / "src/greeting.py").is_file()


@pytest.mark.asyncio
async def test_commit_backfill_done_item_without_sha(
    git_project: Path,
    sample_item: dict,
) -> None:
    from datetime import datetime, timezone

    from todos_tool.manifest import load_workspace, save_item
    from todos_tool.models import ItemStatus

    write_todos(
        git_project,
        [sample_item],
        settings={
            "max_attempts": 1,
            "max_session_restarts_per_phase": 1,
            "work_timeout_seconds": 30,
            "review_timeout_seconds": 30,
            "auto_commit": False,
            "stop_on_failure": True,
            "parse_error_threshold": 20,
        },
    )
    (git_project / "src").mkdir(exist_ok=True)
    (git_project / "src/greeting.py").write_text(
        "def greet(name): return f'hi {name}'\n",
        encoding="utf-8",
    )

    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    item.status = ItemStatus.DONE
    item.result.completed_at = datetime.now(timezone.utc)
    item.result.summary = "Implemented greeting helper"
    save_item(ws, item)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            allow_dirty=False,
            auto_commit=True,
        )
    )
    sha = await orch.commit_item("TASK-001")
    assert sha

    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.result.commit_sha == sha
    assert (git_project / "src/greeting.py").is_file()


@pytest.mark.asyncio
async def test_review_fail_consumes_attempt(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={
            "max_attempts": 2,
            "max_session_restarts_per_phase": 1,
            "work_timeout_seconds": 30,
            "review_timeout_seconds": 30,
            "auto_commit": True,
            "stop_on_failure": True,
            "parse_error_threshold": 20,
        },
    )
    # Always fail review
    wrapper = fake_agent.parent / "agent-fail"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_WRITE_FILE=src/x.py\n"
        "export FAKE_AGENT_DECISION=fail\n"
        # Bump attempt based on existing state if present — keep attempt=1 for simplicity;
        # reviewer mismatch on attempt will also count as fail.
        "export FAKE_AGENT_ATTEMPT=1\n"
        f"exec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    # Smarter wrapper: set attempt from prompt is hard; instead emit matching attempt
    # by reading FAKE_AGENT_ATTEMPT from a counter file.
    counter = fake_agent.parent / "attempt_counter"
    counter.write_text("0", encoding="utf-8")
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, subprocess\n"
        f"counter = {str(counter)!r}\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "args = sys.argv[1:]\n"
        "is_review = '--mode' in args and 'ask' in args\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "env['FAKE_AGENT_ITEM_ID'] = 'TASK-001'\n"
        "env['FAKE_AGENT_WRITE_FILE'] = 'src/x.py'\n"
        "env['FAKE_AGENT_DECISION'] = 'fail'\n"
        "if not is_review:\n"
        "    n = int(open(counter).read() or '0') + 1\n"
        "    open(counter, 'w').write(str(n))\n"
        "    env['FAKE_AGENT_ATTEMPT'] = str(n)\n"
        "else:\n"
        "    env['FAKE_AGENT_ATTEMPT'] = open(counter).read().strip() or '1'\n"
        "raise SystemExit(subprocess.call([sys.executable, agent, *args], env=env))\n",
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
    assert "TASK-001" in report.failed or "TASK-001" in report.blocked
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.BLOCKED


@pytest.mark.asyncio
async def test_duplicate_commit_prevention_on_resume(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    # Simulate completed commit state without item marked done
    runs = git_project / "todos" / "runs" / "TASK-001"
    runs.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "item_id": "TASK-001",
        "logical_attempt": 1,
        "phase": "commit",
        "session_number": 1,
        "session_restart_count": 0,
        "last_transition": "commit_completed",
        "review": {"decision": "pass", "summary": "ok", "issues": []},
        "commit_state": "completed",
        "commit_sha": "deadbeef",
        "baseline_head": "HEAD",
        "work_summary": "done",
        "changed_paths": [],
        "history": [],
    }
    (runs / "state.json").write_text(json.dumps(state), encoding="utf-8")
    item_path = git_project / "todos" / "items" / "001.yaml"
    data = yaml.safe_load(item_path.read_text())
    data["status"] = "in_progress"
    item_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    wrapper = fake_agent.parent / "agent-noop"
    wrapper.write_text(
        f"#!/bin/sh\nexec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    import subprocess

    before = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=git_project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin=str(wrapper),
            skip_probe=True,
            no_color=True,
            allow_dirty=True,
        )
    )
    report = await orch.resume()
    assert report.completed == ["TASK-001"]
    after = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=git_project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert before == after  # no new commit
    ws = load_workspace(git_project)
    assert ws.get("TASK-001").status == ItemStatus.DONE
