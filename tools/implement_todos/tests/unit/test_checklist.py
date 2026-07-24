"""Checklist schema, persistence, and force-reset behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.manifest import load_workspace, save_item
from todos_tool.models import (
    ChecklistItem,
    ItemStatus,
    ItemType,
    TodoItem,
    validate_todo_item,
)
from todos_tool.orchestrator import Orchestrator
from todos_tool.persistence import load_state, new_run_state, record_transition
from todos_tool.run_config import RunConfig
from todos_tool.models import Transition


def test_validate_todo_item_rejects_duplicate_checklist_ids() -> None:
    with pytest.raises(ValueError, match="duplicate checklist id"):
        validate_todo_item(
            {
                "version": 1,
                "id": "TASK-001",
                "title": "Example",
                "type": "feature",
                "description": "Do work.",
                "acceptance_criteria": ["Done."],
                "checklist": [
                    {"id": "ck-a", "text": "First", "done": False},
                    {"id": "ck-a", "text": "Duplicate", "done": False},
                ],
            }
        )


def test_validate_todo_item_rejects_unknown_checklist_fields() -> None:
    with pytest.raises(ValueError, match="Unknown checklist item fields"):
        validate_todo_item(
            {
                "version": 1,
                "id": "TASK-001",
                "title": "Example",
                "type": "feature",
                "description": "Do work.",
                "acceptance_criteria": ["Done."],
                "checklist": [
                    {"id": "ck-a", "text": "First", "done": False, "status": "open"},
                ],
            }
        )


def test_checklist_round_trip_via_todo_item() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="Do work.",
        acceptance_criteria=["Done."],
        checklist=[
            ChecklistItem(id="ck-a", text="First step", done=True),
            ChecklistItem(id="ck-b", text="Second step", done=False),
        ],
    )
    reloaded = TodoItem.from_dict(item.to_dict())
    assert len(reloaded.checklist) == 2
    assert reloaded.checklist[0].id == "ck-a"
    assert reloaded.checklist[0].done is True
    assert reloaded.checklist[1].text == "Second step"


@pytest.mark.asyncio
async def test_force_reset_preserves_checklist_done(
    git_project: Path,
    sample_item: dict,
) -> None:
    sample_item = {
        **sample_item,
        "checklist": [
            {"id": "ck-a", "text": "First", "done": True},
            {"id": "ck-b", "text": "Second", "done": False},
        ],
    }
    write_todos(git_project, [sample_item], settings={"max_attempts": 1, "auto_commit": False})
    ws = load_workspace(git_project)
    item = ws.items[0]
    item.status = ItemStatus.DONE
    save_item(ws, item)
    runs_dir = ws.runs_dir(item.id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    state = new_run_state(item.id, "abc123")
    record_transition(runs_dir, state, Transition.ITEM_DONE)

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
    reloaded = ws.get("TASK-001")
    assert reloaded is not None
    assert reloaded.status == ItemStatus.PENDING
    assert load_state(ws.runs_dir("TASK-001")) is None
    assert reloaded.checklist[0].done is True
    assert reloaded.checklist[1].done is False
