"""Additional orchestrator, git, and persistence coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.errors import GitError
from todos_tool.git_service import head_sha, stage_paths, staged_paths
from todos_tool.manifest import load_workspace, save_item
from todos_tool.models import CommitState, ItemStatus, Phase, Transition
from todos_tool.orchestrator import Orchestrator, RunConfig
from todos_tool.persistence import (
    append_ndjson,
    load_state,
    new_run_state,
    record_transition,
)


def test_append_ndjson_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    append_ndjson(path, {"type": "assistant", "text": "hello"})
    append_ndjson(path, {"type": "done"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "assistant"


def test_stage_paths_allows_extra_todos_metadata(git_project: Path) -> None:
    todos_item = git_project / "todos" / "items" / "001.yaml"
    todos_item.parent.mkdir(parents=True, exist_ok=True)
    todos_item.write_text("id: x\n", encoding="utf-8")
    (git_project / "src").mkdir(exist_ok=True)
    tracked = git_project / "src/change.py"
    tracked.write_text("x = 1\n", encoding="utf-8")

    stage_paths(git_project, ["todos/items/001.yaml"], todos_dir="todos")
    stage_paths(git_project, ["src/change.py"], todos_dir="todos")
    assert set(staged_paths(git_project)) == {
        "todos/items/001.yaml",
        "src/change.py",
    }


@pytest.mark.asyncio
async def test_no_stageable_paths_rolls_back_to_in_progress(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item], settings={"auto_commit": True})
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)
    subprocess.run(["git", "add", "todos"], cwd=git_project, check=True)
    subprocess.run(["git", "commit", "-m", "sync todos metadata"], cwd=git_project, check=True)

    runs_dir = ws.runs_dir(item.id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    state = {
        "schema_version": 1,
        "item_id": item.id,
        "logical_attempt": 1,
        "phase": "commit",
        "session_number": 1,
        "session_restart_count": 0,
        "last_transition": "commit_failed",
        "review": {"decision": "pass", "summary": "ok", "issues": []},
        "commit_state": "failed",
        "baseline_head": baseline,
        "work_summary": "only ignored changes",
        "changed_paths": ["ignored/secret.txt"],
        "history": [],
    }
    (git_project / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    ignored = git_project / "ignored"
    ignored.mkdir()
    (ignored / "secret.txt").write_text("nope\n", encoding="utf-8")
    (runs_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            allow_dirty=True,
        )
    )
    report = await orch.resume()
    assert report.retryable == ["TASK-001"]

    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.IN_PROGRESS
    saved_state = load_state(runs_dir)
    assert saved_state is not None
    assert saved_state.commit_state == CommitState.FAILED


@pytest.mark.asyncio
async def test_resume_after_failed_commit(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item], settings={"auto_commit": True})
    (git_project / "src").mkdir(exist_ok=True)
    (git_project / "src/greeting.py").write_text("x = 1\n", encoding="utf-8")

    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.IN_PROGRESS
    save_item(ws, item)

    runs_dir = ws.runs_dir(item.id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    state = new_run_state(item.id, head_sha(git_project))
    state.logical_attempt = 1
    state.phase = Phase.COMMIT
    state.commit_state = CommitState.FAILED
    state.work_summary = "ready to commit"
    state.review.decision = "pass"
    state.changed_paths = ["src/greeting.py"]
    record_transition(runs_dir, state, Transition.REVIEW_PASSED)
    record_transition(runs_dir, state, Transition.COMMIT_FAILED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            auto_commit=True,
        )
    )
    report = await orch.resume()
    assert report.completed == ["TASK-001"]
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert item.status == ItemStatus.DONE
    assert item.result.commit_sha


@pytest.mark.asyncio
async def test_stop_on_failure_false_continues(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    failing = dict(sample_item)
    passing = dict(sample_item)
    passing["id"] = "TASK-002"
    passing["title"] = "Second task"
    write_todos(
        git_project,
        [failing, {**passing, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "stop_on_failure": False, "auto_commit": True},
    )

    wrapper = fake_agent.parent / "agent-stop-on-false"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, subprocess\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "args = sys.argv[1:]\n"
        "prompt = args[-1] if args else ''\n"
        "prompt_file = os.environ.get('TODOS_TOOL_PROMPT_FILE')\n"
        "if prompt_file and os.path.isfile(prompt_file):\n"
        "    prompt = open(prompt_file).read()\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "if 'TASK-002' in prompt:\n"
        "    env['FAKE_AGENT_ITEM_ID'] = 'TASK-002'\n"
        "    env['FAKE_AGENT_WRITE_FILE'] = 'src/second.py'\n"
        "    env['FAKE_AGENT_DECISION'] = 'pass'\n"
        "else:\n"
        "    env['FAKE_AGENT_ITEM_ID'] = 'TASK-001'\n"
        "    env['FAKE_AGENT_DECISION'] = 'fail'\n"
        "    env['FAKE_AGENT_WRITE_FILE'] = 'src/first.py'\n"
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
            stop_on_failure=False,
        )
    )
    report = await orch.run()
    assert report.blocked == ["TASK-001"]
    assert report.completed == ["TASK-002"]


@pytest.mark.asyncio
async def test_backfill_rejects_unrelated_dirty_file(
    git_project: Path,
    sample_item: dict,
) -> None:
    from datetime import datetime, timezone

    write_todos(git_project, [sample_item], settings={"auto_commit": True})
    (git_project / "src").mkdir(exist_ok=True)
    (git_project / "src/greeting.py").write_text("x = 1\n", encoding="utf-8")
    (git_project / "noise.txt").write_text("unrelated\n", encoding="utf-8")

    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    item.status = ItemStatus.DONE
    item.result.completed_at = datetime.now(timezone.utc)
    item.result.summary = "done"
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
    runs_dir = git_project / "todos" / "runs" / "TASK-001"
    runs_dir.mkdir(parents=True, exist_ok=True)
    from todos_tool.persistence import new_run_state, save_state

    state = new_run_state("TASK-001", head_sha(git_project))
    state.changed_paths = ["src/greeting.py"]
    save_state(runs_dir, state)

    with pytest.raises(GitError, match="unrelated"):
        await orch.commit_item("TASK-001")
