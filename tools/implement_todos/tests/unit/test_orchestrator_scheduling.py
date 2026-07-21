"""Orchestrator scheduling and reporting tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.errors import SchedulingError
from todos_tool.manifest import load_workspace
from todos_tool.models import ItemStatus
from todos_tool.orchestrator import Orchestrator, RunConfig
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
