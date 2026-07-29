"""Regression tests for orchestrator hardening."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.errors import GitError, PersistenceError, TodosToolError
from todos_tool.git_service import (
    capture_pre_dirty_fingerprints,
    fingerprint_path,
    head_sha,
    paths_overlap,
    staged_paths,
    status,
    verify_commit_sha,
    verify_pre_dirty_unchanged,
)
from todos_tool.manifest import load_workspace, save_item
from todos_tool.models import (
    ItemStatus,
    Phase,
    Transition,
    ValidationCommandResult,
)
from todos_tool.orchestrator import Orchestrator, RunConfig
from todos_tool.persistence import load_state, new_run_state, record_transition, save_state
from todos_tool.prompts import build_review_prompt
from todos_tool.validation_runner import run_validation_commands


def test_paths_overlap_normalizes_trailing_slash() -> None:
    assert paths_overlap("src/", "src/greeting.py")
    assert paths_overlap("src", "src/greeting.py")


def test_status_parses_paths_with_spaces(git_project: Path) -> None:
    spaced = git_project / "my file.txt"
    spaced.write_text("x", encoding="utf-8")
    st = status(git_project)
    assert "my file.txt" in st.changed_paths


def test_pre_dirty_modification_fails(git_project: Path) -> None:
    dirty = git_project / "preexisting.txt"
    dirty.write_text("before", encoding="utf-8")
    fingerprints = capture_pre_dirty_fingerprints(git_project, {"preexisting.txt"})
    dirty.write_text("after", encoding="utf-8")
    with pytest.raises(GitError, match="already dirty"):
        verify_pre_dirty_unchanged(
            git_project,
            fingerprints,
            item_id="TASK-001",
        )


def test_verify_commit_sha_rejects_invalid(git_project: Path) -> None:
    with pytest.raises(PersistenceError, match="not found"):
        verify_commit_sha(git_project, "deadbeef")


def test_review_prompt_includes_diff_with_continuation() -> None:
    from todos_tool.models import ItemType, TodoItem

    item = TodoItem(
        id="TASK-001",
        title="Title",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
    )
    prompt = build_review_prompt(
        item,
        logical_attempt=1,
        resolved_commands=["pytest"],
        work_summary="summary",
        git_diff="diff --git a/x b/x",
        git_status=" M x",
        continuation="Session restart context",
    )
    assert "## Current git status" in prompt
    assert "## Current git diff" in prompt
    assert "Session restart context" in prompt
    assert "Review submission tool" in prompt


@pytest.mark.asyncio
async def test_run_rejects_in_progress_item(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)

    orch = Orchestrator(
        RunConfig(workspace_root=git_project, skip_probe=True, no_color=True)
    )
    with pytest.raises(TodosToolError, match="already in progress"):
        await orch.run()


@pytest.mark.asyncio
async def test_run_rejects_other_in_progress_when_targeting_todo(
    git_project: Path,
    sample_item: dict,
) -> None:
    active = dict(sample_item)
    other = dict(sample_item)
    other["id"] = "TASK-002"
    other["title"] = "Other task"
    write_todos(
        git_project,
        [active, {**other, "_file": "items/002.yaml"}],
    )
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)

    orch = Orchestrator(
        RunConfig(workspace_root=git_project, skip_probe=True, no_color=True)
    )
    with pytest.raises(TodosToolError, match="TASK-001.*already in progress"):
        await orch.run(todo_id="TASK-002")


@pytest.mark.asyncio
async def test_resume_after_work_phase_ready_runs_validation_then_review(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={"max_attempts": 1, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
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
    record_transition(runs_dir, state, Transition.WORK_PHASE_READY)

    wrapper = fake_agent.parent / "agent-review-only"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_ATTEMPT=1\n"
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
    report = await orch.resume()
    assert report.completed == ["TASK-001"]
    saved = load_state(runs_dir)
    assert saved is not None
    assert saved.phase == Phase.IDLE
    assert not (runs_dir / "attempts" / "01" / "work-session-2.ndjson").exists()


@pytest.mark.asyncio
async def test_stop_on_failure_stops_on_blocked(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    failing = dict(sample_item)
    passing = dict(sample_item)
    passing["id"] = "TASK-002"
    passing["title"] = "Second"
    passing["priority"] = 200
    write_todos(
        git_project,
        [failing, {**passing, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "stop_on_failure": True, "auto_commit": True},
    )

    wrapper = fake_agent.parent / "agent-block-stop"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, subprocess\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "args = sys.argv[1:]\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "if 'TASK-002' in open(os.environ.get('TODOS_TOOL_PROMPT_FILE', ''), encoding='utf-8').read() if os.environ.get('TODOS_TOOL_PROMPT_FILE') else False:\n"
        "    env['FAKE_AGENT_ITEM_ID'] = 'TASK-002'\n"
        "    env['FAKE_AGENT_WRITE_FILE'] = 'src/second.py'\n"
        "    env['FAKE_AGENT_DECISION'] = 'pass'\n"
        "else:\n"
        "    env['FAKE_AGENT_ITEM_ID'] = 'TASK-001'\n"
        "    env['FAKE_AGENT_WRITE_FILE'] = 'src/first.py'\n"
        "    env['FAKE_AGENT_DECISION'] = 'blocked'\n"
        "env['FAKE_AGENT_ATTEMPT'] = '1'\n"
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
            stop_on_failure=True,
        )
    )
    report = await orch.run()
    assert "TASK-001" in report.blocked
    assert report.completed == []


def _stop_pid(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.mark.asyncio
async def test_resume_refuses_live_agent_pid(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
    tmp_path: Path,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)

    wrapper = tmp_path / "agent-sleep"
    wrapper.write_text(
        "#!/bin/sh\n"
        "export FAKE_AGENT_MODE=timeout\n"
        "export FAKE_AGENT_SLEEP=60\n"
        f"exec python3 '{fake_agent}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    runs_dir = ws.runs_dir(item.id)
    state = new_run_state(item.id, subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=git_project, text=True
    ).strip())
    state.phase = Phase.WORK
    state.logical_attempt = 1
    save_state(runs_dir, state)

    from todos_tool.cursor_client import CursorClient

    client = CursorClient(agent_bin=str(wrapper), skip_probe=True, no_color=True)
    prompt_path = runs_dir / "attempts" / "01" / "work-prompt-1.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("# work\n", encoding="utf-8")
    started: list[int] = []

    task = __import__("asyncio").create_task(
        client.run_session(
            workspace=git_project,
            prompt="ignored",
            prompt_path=prompt_path,
            phase="work",
            timeout_seconds=60,
            on_agent_started=started.append,
        )
    )
    for _ in range(40):
        if started:
            break
        await __import__("asyncio").sleep(0.05)
    assert started
    state.agent_pid = started[0]
    save_state(runs_dir, state)

    dry_orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            dry_run_prompts=True,
        )
    )
    with pytest.raises(TodosToolError, match="still running"):
        await dry_orch.resume()

    orch = Orchestrator(
        RunConfig(workspace_root=git_project, skip_probe=True, no_color=True)
    )
    with pytest.raises(TodosToolError, match="still running"):
        await orch.resume()

    task.cancel()
    with pytest.raises(TodosToolError, match="Interrupted"):
        await task


@pytest.mark.asyncio
async def test_allow_dirty_whole_worktree_commits_preexisting_changes(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    pre = git_project / "preexisting.txt"
    pre.write_text("unchanged\n", encoding="utf-8")
    write_todos(
        git_project,
        [sample_item],
        settings={"max_attempts": 1, "auto_commit": True},
    )

    wrapper = fake_agent.parent / "agent-touch-pre-dirty"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
        "export FAKE_AGENT_ITEM_ID=TASK-001\n"
        "export FAKE_AGENT_WRITE_FILE=preexisting.txt\n"
        "export FAKE_AGENT_WRITE_CONTENT='agent changed this\\n'\n"
        "export FAKE_AGENT_DECISION=pass\n"
        "export FAKE_AGENT_ATTEMPT=1\n"
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
            allow_dirty=True,
        )
    )
    report = await orch.run(todo_id="TASK-001")
    assert report.completed == ["TASK-001"]
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.DONE
    assert "agent changed this" in pre.read_text(encoding="utf-8")


def test_staged_paths_nul_safe(git_project: Path) -> None:
    spaced = git_project / "my file.txt"
    spaced.write_text("x", encoding="utf-8")
    from todos_tool.git_service import stage_paths

    stage_paths(git_project, ["my file.txt"])
    assert staged_paths(git_project) == ["my file.txt"]


def test_fingerprint_tracks_content_change(git_project: Path) -> None:
    path = git_project / "tracked.txt"
    path.write_text("v1", encoding="utf-8")
    first = fingerprint_path(git_project, "tracked.txt")
    path.write_text("v2", encoding="utf-8")
    second = fingerprint_path(git_project, "tracked.txt")
    assert first != second


@pytest.mark.asyncio
async def test_validation_runner_records_authoritative_results(
    git_project: Path,
) -> None:
    python = shlex.quote(sys.executable)
    results = await run_validation_commands(
        git_project,
        [
            f'{python} -c "print(\'ok\')"',
            f'{python} -c "import sys; sys.exit(3)"',
        ],
        timeout_seconds=10,
    )
    assert [(result.passed, result.exit_code) for result in results] == [
        (True, 0),
        (False, 3),
    ]
    assert results[0].summary == "ok"


@pytest.mark.asyncio
async def test_validation_runner_times_out_process_group(
    git_project: Path,
) -> None:
    python = shlex.quote(sys.executable)
    started = time.monotonic()
    results = await run_validation_commands(
        git_project,
        [f'{python} -c "import time; time.sleep(30)"'],
        timeout_seconds=1,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 8
    assert results[0].passed is False
    assert results[0].exit_code == 124
    assert "Timed out after 1s" in results[0].summary


@pytest.mark.asyncio
async def test_dry_run_only_writes_prompt_previews(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    item_path = git_project / "todos" / "items" / "001.yaml"
    before = item_path.read_bytes()

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            agent_bin="/definitely/not/an/agent",
            skip_probe=True,
            no_color=True,
            dry_run_prompts=True,
        )
    )
    report = await orch.run(todo_id="TASK-001")

    assert report.planned == ["TASK-001"]
    assert report.completed == []
    assert item_path.read_bytes() == before
    runs_dir = git_project / "todos" / "runs" / "TASK-001"
    assert not (runs_dir / "state.json").exists()
    assert (runs_dir / "dry-run" / "work-prompt.md").is_file()
    review_prompt = (runs_dir / "dry-run" / "review-prompt.md").read_text(
        encoding="utf-8"
    )
    assert "not executed in prompt-only dry run" in review_prompt


@pytest.mark.asyncio
async def test_resume_dry_run_uses_persisted_state_without_mutating_it(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)

    changed = git_project / "src" / "existing.py"
    changed.parent.mkdir()
    changed.write_text("value = 1\n", encoding="utf-8")

    runs_dir = ws.runs_dir(item.id)
    state = new_run_state(item.id, head_sha(git_project))
    state.logical_attempt = 3
    state.phase = Phase.REVIEW
    state.work_summary = "persisted work summary"
    state.validation_attempt = 3
    state.validation_results = [
        ValidationCommandResult(
            command="pytest",
            passed=True,
            exit_code=0,
            summary="105 passed",
        )
    ]
    record_transition(runs_dir, state, Transition.REVIEW_SESSION_STARTED)
    state_path = runs_dir / "state.json"
    before = state_path.read_bytes()

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            dry_run_prompts=True,
        )
    )
    report = await orch.resume()

    assert report.planned == ["TASK-001"]
    assert state_path.read_bytes() == before
    review_prompt = (runs_dir / "dry-run" / "review-prompt.md").read_text(
        encoding="utf-8"
    )
    assert "**Logical attempt:** 3" in review_prompt
    assert "persisted work summary" in review_prompt
    assert "passed=true exit_code=0" in review_prompt
    assert "src/existing.py" in review_prompt


@pytest.mark.asyncio
async def test_resume_dry_run_enforces_dirty_tree_preflight(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)
    unrelated = git_project / "unrelated.txt"
    unrelated.write_text("before\n", encoding="utf-8")
    state = new_run_state(item.id, head_sha(git_project))
    state.logical_attempt = 1
    state.phase = Phase.WORK
    state.pre_dirty_fingerprints = capture_pre_dirty_fingerprints(
        git_project,
        {"unrelated.txt"},
    )
    save_state(ws.runs_dir(item.id), state)
    unrelated.write_text("after\n", encoding="utf-8")

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            dry_run_prompts=True,
        )
    )
    with pytest.raises(GitError, match="already dirty"):
        await orch.resume()

    assert not (ws.runs_dir(item.id) / "dry-run").exists()
