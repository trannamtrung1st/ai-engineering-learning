"""Orchestrator scheduling and reporting tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers import write_todos
from todos_tool.errors import SchedulingError
from todos_tool.manifest import load_workspace, save_item
from todos_tool.models import ItemStatus, Phase, Transition
from todos_tool.orchestrator import Orchestrator, RunConfig
from todos_tool.persistence import load_state, new_run_state, record_transition
from todos_tool.scheduler import list_ready


@pytest.mark.asyncio
async def test_unknown_todo_raises(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    orch = Orchestrator(
        RunConfig(workspace_root=git_project, skip_probe=True, no_color=True)
    )
    with pytest.raises(SchedulingError, match="Unknown item id"):
        await orch.run(todo_id="TASK-404")


def test_priority_order(git_project: Path, sample_item: dict) -> None:
    low = dict(sample_item)
    high = dict(sample_item)
    high["id"] = "TASK-002"
    high["priority"] = 10
    high["title"] = "High priority"
    write_todos(
        git_project,
        [low, {**high, "_file": "items/002.yaml"}],
    )
    ws = load_workspace(git_project)
    ready = list_ready(ws)
    assert [item.id for item in ready] == ["TASK-002", "TASK-001"]


@pytest.mark.asyncio
async def test_superseded_reported_as_skipped(
    git_project: Path,
    sample_item: dict,
) -> None:
    from todos_tool.continuation import apply_restructure_proposal
    from todos_tool.models import RestructuringProposal

    write_todos(git_project, [sample_item], settings={"max_attempts": 1})
    ws = load_workspace(git_project)
    item = ws.items[0]
    proposal = RestructuringProposal(
        item_id=item.id,
        supersede=True,
        new_items=[
            {
                "version": 1,
                "id": "TASK-010",
                "title": "Follow-up",
                "type": "feature",
                "description": "Split work",
                "acceptance_criteria": ["Follow-up done"],
                "file": "items/010.yaml",
            }
        ],
    )
    apply_restructure_proposal(ws, item, proposal)
    ws = load_workspace(git_project)
    assert ws.get("TASK-001").status == ItemStatus.SUPERSEDED

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            dry_run_prompts=True,
        )
    )
    # Superseded item should not be picked in unconstrained run
    report = await orch.run()
    assert report.skipped == []
    assert report.completed == []


@pytest.mark.asyncio
async def test_resume_continues_with_next_ready_item(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
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

    wrapper = fake_agent.parent / "agent-resume-continue"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
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
    assert report.completed == ["TASK-001", "TASK-002"]


@pytest.mark.asyncio
async def test_resume_honors_stop_on_failure_for_later_items(
    fake_agent: Path,
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "stop_on_failure": True, "auto_commit": False},
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

    wrapper = fake_agent.parent / "agent-resume-stop"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, subprocess\n"
        f"agent = {str(fake_agent)!r}\n"
        f"workspace = {str(git_project)!r}\n"
        "args = sys.argv[1:]\n"
        "env = os.environ.copy()\n"
        "env['FAKE_AGENT_WORKSPACE'] = workspace\n"
        "prompt_file = os.environ.get('TODOS_TOOL_PROMPT_FILE', '')\n"
        "prompt = open(prompt_file, encoding='utf-8').read() if prompt_file else ''\n"
        "if 'TASK-002' in prompt:\n"
        "    env['FAKE_AGENT_DECISION'] = 'blocked'\n"
        "else:\n"
        "    env['FAKE_AGENT_DECISION'] = 'pass'\n"
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
    report = await orch.resume()
    assert report.completed == ["TASK-001"]
    assert report.blocked == ["TASK-002"]


@pytest.mark.asyncio
async def test_force_reset_resets_all_items(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    third = dict(sample_item)
    third["id"] = "TASK-003"
    third["title"] = "Third task"
    third["priority"] = 300
    write_todos(
        git_project,
        [
            sample_item,
            {**second, "_file": "items/002.yaml"},
            {**third, "_file": "items/003.yaml"},
        ],
        settings={"max_attempts": 1, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    for item in ws.items:
        item.status = ItemStatus.BLOCKED
        save_item(ws, item)
        runs_dir = ws.runs_dir(item.id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        state = new_run_state(item.id, "abc123")
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            force_reset=True,
            dry_run_prompts=True,
        )
    )
    await orch.run()

    ws = load_workspace(git_project)
    for item_id in ("TASK-001", "TASK-002", "TASK-003"):
        assert ws.get(item_id).status == ItemStatus.PENDING
        assert load_state(ws.runs_dir(item_id)) is None


@pytest.mark.asyncio
async def test_force_reset_includes_done_items(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    done_item = ws.items[0]
    done_item.status = ItemStatus.DONE
    done_item.result.summary = "finished earlier"
    done_item.result.commit_sha = "abc123"
    save_item(ws, done_item)

    blocked_item = ws.items[1]
    blocked_item.status = ItemStatus.BLOCKED
    save_item(ws, blocked_item)

    for item in ws.items:
        runs_dir = ws.runs_dir(item.id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        state = new_run_state(item.id, "abc123")
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            force_reset=True,
            dry_run_prompts=True,
        )
    )
    await orch.run()

    ws = load_workspace(git_project)
    for item_id in ("TASK-001", "TASK-002"):
        item = ws.get(item_id)
        assert item.status == ItemStatus.PENDING
        assert item.result.summary is None
        assert item.result.commit_sha is None
        assert load_state(ws.runs_dir(item_id)) is None


@pytest.mark.asyncio
async def test_resume_force_reset_resets_all_items(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    ws.items[0].status = ItemStatus.IN_PROGRESS
    save_item(ws, ws.items[0])
    ws.items[1].status = ItemStatus.BLOCKED
    save_item(ws, ws.items[1])

    for item in ws.items:
        runs_dir = ws.runs_dir(item.id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        state = new_run_state(item.id, "abc123")
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            force_reset=True,
            dry_run_prompts=True,
        )
    )
    await orch.resume()

    ws = load_workspace(git_project)
    assert ws.get("TASK-001").status == ItemStatus.PENDING
    assert ws.get("TASK-002").status == ItemStatus.PENDING
    assert load_state(ws.runs_dir("TASK-001")) is None
    assert load_state(ws.runs_dir("TASK-002")) is None


@pytest.mark.asyncio
async def test_force_reset_includes_superseded_items(
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
    item.status = ItemStatus.SUPERSEDED
    item.result.summary = "replaced by restructure"
    save_item(ws, item)

    runs_dir = ws.runs_dir(item.id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    state = new_run_state(item.id, "abc123")
    record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            force_reset=True,
            dry_run_prompts=True,
        )
    )
    await orch.run()

    ws = load_workspace(git_project)
    refreshed = ws.get("TASK-001")
    assert refreshed.status == ItemStatus.PENDING
    assert refreshed.result.summary is None
    assert load_state(ws.runs_dir("TASK-001")) is None


@pytest.mark.asyncio
async def test_force_reset_scoped_leaves_other_done_items(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    done_item = ws.items[0]
    done_item.status = ItemStatus.DONE
    done_item.result.summary = "finished"
    done_item.result.commit_sha = "abc123"
    save_item(ws, done_item)

    blocked_item = ws.items[1]
    blocked_item.status = ItemStatus.BLOCKED
    save_item(ws, blocked_item)

    for item in ws.items:
        runs_dir = ws.runs_dir(item.id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        state = new_run_state(item.id, "abc123")
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            force_reset=True,
            dry_run_prompts=True,
        )
    )
    await orch.run(todo_id="TASK-002")

    ws = load_workspace(git_project)
    assert ws.get("TASK-001").status == ItemStatus.DONE
    assert ws.get("TASK-001").result.commit_sha == "abc123"
    assert load_state(ws.runs_dir("TASK-001")) is not None
    assert ws.get("TASK-002").status == ItemStatus.PENDING
    assert load_state(ws.runs_dir("TASK-002")) is None


@pytest.mark.asyncio
async def test_force_reset_scoped_to_todo_flag(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
        settings={"max_attempts": 1, "auto_commit": False},
    )
    ws = load_workspace(git_project)
    for item in ws.items:
        item.status = ItemStatus.BLOCKED
        save_item(ws, item)
        runs_dir = ws.runs_dir(item.id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        state = new_run_state(item.id, "abc123")
        record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    orch = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            force_reset=True,
            dry_run_prompts=True,
        )
    )
    await orch.run(todo_id="TASK-002")

    ws = load_workspace(git_project)
    assert ws.get("TASK-001").status == ItemStatus.BLOCKED
    assert ws.get("TASK-002").status == ItemStatus.PENDING
    assert load_state(ws.runs_dir("TASK-001")) is not None
    assert load_state(ws.runs_dir("TASK-002")) is None


@pytest.mark.asyncio
async def test_force_reset_clears_run_state_then_executes(
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
    item.status = ItemStatus.BLOCKED
    save_item(ws, item)

    runs_dir = ws.runs_dir(item.id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    state = new_run_state(item.id, "abc123")
    record_transition(runs_dir, state, Transition.ITEM_BLOCKED)

    wrapper = fake_agent.parent / "agent-force-reset"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"export FAKE_AGENT_WORKSPACE='{git_project}'\n"
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
            force_reset=True,
        )
    )
    report = await orch.run()
    assert report.completed == ["TASK-001"]
    ws = load_workspace(git_project)
    assert ws.get("TASK-001").status == ItemStatus.DONE
    saved = load_state(runs_dir)
    assert saved is not None
    assert saved.phase == Phase.IDLE
    assert saved.last_transition != Transition.ITEM_BLOCKED


@patch("todos_tool.orchestrator.notify_item_done")
def test_maybe_notify_item_done_respects_config(
    mock_notify_item_done,
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.DONE
    item.result.commit_sha = "abc123456789"
    save_item(ws, item)

    enabled = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            notify_per_item=True,
        )
    )
    enabled.workspace = ws
    enabled._maybe_notify_item_done(item.id)
    mock_notify_item_done.assert_called_once_with(
        enabled=True,
        item_id=item.id,
        title=item.title,
        commit_sha="abc123456789",
    )

    mock_notify_item_done.reset_mock()
    disabled = Orchestrator(
        RunConfig(
            workspace_root=git_project,
            skip_probe=True,
            no_color=True,
            notify_per_item=False,
        )
    )
    disabled.workspace = ws
    disabled._maybe_notify_item_done(item.id)
    mock_notify_item_done.assert_not_called()
