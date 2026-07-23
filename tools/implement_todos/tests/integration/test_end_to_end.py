"""Integration tests using the fake Cursor agent."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest
import yaml

from tests.helpers import write_todos
from todos_tool.cursor_client import CursorClient
from todos_tool.errors import CursorSessionError, TodosToolError
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
    validation_path = (
        git_project
        / "todos"
        / "runs"
        / "TASK-001"
        / "attempts"
        / "01"
        / "validation-results.json"
    )
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["results"][0]["command"] == "pytest"
    assert validation["results"][0]["passed"] is True
    review_prompt = (
        validation_path.parent / "review-prompt-1.md"
    ).read_text(encoding="utf-8")
    assert "Authoritative orchestrator validation" in review_prompt
    assert "passed=true exit_code=0" in review_prompt
    assert "Commit subject guidance" in review_prompt
    assert "proposed_commit_message" in review_prompt
    submission_path = validation_path.parent / "review-submission-1.json"
    assert submission_path.is_file()
    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    assert submission["decision"] == "pass"

    # Exactly one new commit beyond initial
    import subprocess

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=git_project,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "finalize worktree" in log.stdout or "implement reviewed change" in log.stdout
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
        "is_review = False\n"
        "prompt_file = os.environ.get('TODOS_TOOL_PROMPT_FILE', '')\n"
        "if prompt_file and os.path.isfile(prompt_file):\n"
        "    prompt_text = open(prompt_file, encoding='utf-8').read()\n"
        "    is_review = 'Independent review session' in prompt_text\n"
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
    assert report.blocked == ["TASK-001"]
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.BLOCKED


@pytest.mark.asyncio
async def test_validation_failure_skips_review(
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
            "auto_commit": False,
            "validation_timeout_seconds": 30,
            "project_check": command,
        },
    )

    claimed_validation = json.dumps(
        [
            {
                "command": command,
                "passed": True,
                "exit_code": 0,
                "summary": "claimed pass",
            }
        ]
    )
    wrapper = fake_agent.parent / "agent-validation-disagreement"
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
        "env['FAKE_AGENT_WRITE_FILE'] = 'src/result.py'\n"
        f"env['FAKE_AGENT_VALIDATION_JSON'] = {claimed_validation!r}\n"
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

    assert report.blocked == ["TASK-001"]
    validation_path = (
        git_project
        / "todos"
        / "runs"
        / "TASK-001"
        / "attempts"
        / "01"
        / "validation-results.json"
    )
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["results"][0]["passed"] is False
    assert validation["results"][0]["exit_code"] == 3
    assert not list(validation_path.parent.glob("review-session-*.ndjson"))


@pytest.mark.asyncio
async def test_retryable_resume_failure_can_succeed_on_next_resume(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={"max_attempts": 2, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    from todos_tool.manifest import save_item
    from todos_tool.models import Phase, Transition
    from todos_tool.persistence import new_run_state, record_transition
    from todos_tool.git_service import head_sha

    save_item(ws, item)
    runs_dir = ws.runs_dir(item.id)
    state = new_run_state(item.id, head_sha(git_project))
    state.logical_attempt = 1
    state.phase = Phase.REVIEW
    state.work_summary = "attempt one work"
    record_transition(runs_dir, state, Transition.REVIEW_SESSION_STARTED)

    fail_wrapper = fake_agent.parent / "agent-resume-fail"
    fail_wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_ATTEMPT=1\n"
        "export FAKE_AGENT_DECISION=fail\n"
        f"exec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    fail_wrapper.chmod(0o755)

    first = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin=str(fail_wrapper),
            skip_probe=True,
            no_color=True,
        )
    )
    first_report = await first.resume()
    assert first_report.retryable == ["TASK-001"]
    assert load_workspace(git_project).get("TASK-001").status == ItemStatus.IN_PROGRESS

    pass_wrapper = fake_agent.parent / "agent-resume-pass"
    pass_wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_ATTEMPT=2\n"
        "export FAKE_AGENT_DECISION=pass\n"
        "export FAKE_AGENT_WRITE_FILE=src/recovered.py\n"
        f"exec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    pass_wrapper.chmod(0o755)

    second = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin=str(pass_wrapper),
            skip_probe=True,
            no_color=True,
        )
    )
    second_report = await second.resume()
    assert second_report.completed == ["TASK-001"]
    assert load_workspace(git_project).get("TASK-001").status == ItemStatus.DONE


@pytest.mark.asyncio
async def test_duplicate_commit_prevention_on_resume(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    # Simulate completed commit state without item marked done
    import subprocess

    real_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    runs = git_project / "todos" / "runs" / "TASK-001"
    runs.mkdir(parents=True)
    state = {
        "schema_version": 2,
        "item_id": "TASK-001",
        "logical_attempt": 1,
        "phase": "commit",
        "session_number": 1,
        "session_restart_count": 0,
        "last_transition": "commit_completed",
        "review": {"decision": "pass", "summary": "ok", "issues": []},
        "commit_state": "completed",
        "commit_sha": real_sha,
        "baseline_head": real_sha,
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


@pytest.mark.asyncio
async def test_review_chat_json_without_artifact_is_ignored(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={
            "max_attempts": 1,
            "max_session_restarts_per_phase": 1,
            "work_timeout_seconds": 30,
            "review_timeout_seconds": 30,
            "auto_commit": True,
            "stop_on_failure": True,
            "parse_error_threshold": 20,
        },
    )
    wrapper = fake_agent.parent / "agent-chat-only"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_WRITE_FILE=src/greeting.py\n"
        "export FAKE_AGENT_DECISION=pass\n"
        "export FAKE_AGENT_EMIT_CHAT_JSON=1\n"
        "export FAKE_AGENT_SKIP_SUBMIT=1\n"
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
            no_auto_repair_yaml=True,
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.blocked == ["TASK-001"]
    assert "artifact contract failed" in report.errors["TASK-001"]

    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.BLOCKED


@pytest.mark.asyncio
async def test_missing_review_artifact_restarts_review_only(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={
            "max_attempts": 3,
            "max_session_restarts_per_phase": 1,
            "work_timeout_seconds": 30,
            "review_timeout_seconds": 30,
            "auto_commit": True,
            "stop_on_failure": True,
            "parse_error_threshold": 20,
        },
    )
    counter = fake_agent.parent / "review_submit_counter"
    counter.write_text("0", encoding="utf-8")
    wrapper = fake_agent.parent / "agent-missing-then-submit"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, subprocess\n"
        f"counter = {str(counter)!r}\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "args = sys.argv[1:]\n"
        "is_review = False\n"
        "prompt_file = os.environ.get('TODOS_TOOL_PROMPT_FILE', '')\n"
        "if prompt_file and os.path.isfile(prompt_file):\n"
        "    prompt_text = open(prompt_file, encoding='utf-8').read()\n"
        "    is_review = 'Independent review session' in prompt_text\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "env['FAKE_AGENT_ITEM_ID'] = 'TASK-001'\n"
        "env['FAKE_AGENT_WRITE_FILE'] = 'src/greeting.py'\n"
        "env['FAKE_AGENT_DECISION'] = 'pass'\n"
        "if is_review:\n"
        "    n = int(open(counter).read() or '0') + 1\n"
        "    open(counter, 'w').write(str(n))\n"
        "    if n == 1:\n"
        "        env['FAKE_AGENT_SKIP_SUBMIT'] = '1'\n"
        "else:\n"
        "    env['FAKE_AGENT_ATTEMPT'] = '1'\n"
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
    assert report.completed == ["TASK-001"]
    assert counter.read_text(encoding="utf-8").strip() == "2"
    attempt_dir = (
        git_project / "todos" / "runs" / "TASK-001" / "attempts" / "01"
    )
    assert (attempt_dir / "review-session-1.ndjson").is_file()
    assert (attempt_dir / "review-session-2.ndjson").is_file()
    assert not (attempt_dir / "work-session-2.ndjson").exists()
