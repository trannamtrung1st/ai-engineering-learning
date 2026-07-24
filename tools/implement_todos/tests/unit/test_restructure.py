"""Controlled restructuring validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.helpers import write_todos
from todos_tool.continuation import apply_restructure_proposal, load_restructure_proposal
from todos_tool.errors import RestructuringError
from todos_tool.manifest import load_workspace
from todos_tool.models import ChecklistMove, ItemStatus, RestructuringProposal


def test_reject_weakening_via_invalid_new_item(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    proposal = RestructuringProposal(
        item_id=item.id,
        new_items=[
            {
                "version": 1,
                "id": "TASK-001",  # duplicate
                "title": "dup",
                "type": "feature",
                "description": "x",
                "acceptance_criteria": ["a"],
                "file": "items/dup.yaml",
            }
        ],
    )
    with pytest.raises(RestructuringError):
        apply_restructure_proposal(ws, item, proposal)


def test_supersede_and_add_followup(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    proposal = RestructuringProposal(
        item_id=item.id,
        supersede=True,
        new_items=[
            {
                "version": 1,
                "id": "TASK-010",
                "title": "Split part A",
                "type": "feature",
                "status": "pending",
                "description": "Part A",
                "acceptance_criteria": ["Part A done"],
                "file": "items/010-part-a.yaml",
            }
        ],
    )
    reloaded = apply_restructure_proposal(ws, item, proposal)
    assert reloaded.get("TASK-001").status == ItemStatus.SUPERSEDED
    assert reloaded.get("TASK-010") is not None


def test_load_proposal_file(tmp_path: Path) -> None:
    path = tmp_path / "restructure-proposal.json"
    path.write_text(
        '{"schema_version":1,"item_id":"TASK-001","supersede":false,"new_items":[]}',
        encoding="utf-8",
    )
    proposal = load_restructure_proposal(path)
    assert proposal is not None
    assert proposal.item_id == "TASK-001"


def test_dependency_updates_apply_to_new_items(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    proposal = RestructuringProposal(
        item_id=item.id,
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
        dependency_updates={"TASK-010": ["TASK-001"]},
    )
    reloaded = apply_restructure_proposal(ws, item, proposal)
    follow_up = reloaded.get("TASK-010")
    assert follow_up is not None
    assert follow_up.depends_on == ["TASK-001"]


def test_late_validation_failure_leaves_workspace_unchanged(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    manifest_before = (git_project / "todos/manifest.yaml").read_text(encoding="utf-8")
    item_before = (git_project / "todos/items/001.yaml").read_text(encoding="utf-8")
    proposal = RestructuringProposal(
        item_id=item.id,
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
        dependency_updates={"TASK-010": ["TASK-999"]},
    )
    with pytest.raises(RestructuringError):
        apply_restructure_proposal(ws, item, proposal)
    assert (git_project / "todos/manifest.yaml").read_text(encoding="utf-8") == manifest_before
    assert (git_project / "todos/items/001.yaml").read_text(encoding="utf-8") == item_before
    assert not (git_project / "todos/items/010.yaml").exists()


def test_proposal_archived_after_apply(
    git_project: Path,
    sample_item: dict,
    tmp_path: Path,
) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.items[0]
    proposal_path = ws.runs_dir(item.id) / "restructure-proposal.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal = RestructuringProposal(
        item_id=item.id,
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
    proposal_path.write_text(proposal.model_dump_json(), encoding="utf-8")
    apply_restructure_proposal(ws, item, proposal, proposal_path=proposal_path)
    assert not proposal_path.exists()
    assert proposal_path.with_suffix(".applied.json").exists()


def test_checklist_moves_transfer_entry(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["priority"] = 200
    second["checklist"] = []
    sample_item = {
        **sample_item,
        "checklist": [
            {"id": "ck-tests", "text": "Add tests", "done": True},
            {"id": "ck-docs", "text": "Update docs", "done": False},
        ],
    }
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
    )
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    proposal = RestructuringProposal(
        item_id=item.id,
        checklist_moves=[
            ChecklistMove(id="ck-tests", to_item_id="TASK-002"),
        ],
    )
    reloaded = apply_restructure_proposal(ws, item, proposal)
    source = reloaded.get("TASK-001")
    target = reloaded.get("TASK-002")
    assert source is not None
    assert target is not None
    assert [entry.id for entry in source.checklist] == ["ck-docs"]
    assert len(target.checklist) == 1
    assert target.checklist[0].id == "ck-tests"
    assert target.checklist[0].text == "Add tests"
    assert target.checklist[0].done is True


def test_checklist_moves_reject_missing_source_entry(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
    )
    ws = load_workspace(git_project)
    item = ws.items[0]
    proposal = RestructuringProposal(
        item_id=item.id,
        checklist_moves=[
            ChecklistMove(id="ck-missing", to_item_id="TASK-002"),
        ],
    )
    with pytest.raises(RestructuringError, match="missing checklist entry"):
        apply_restructure_proposal(ws, item, proposal)


def test_checklist_moves_reject_target_collision(
    git_project: Path,
    sample_item: dict,
) -> None:
    second = dict(sample_item)
    second["id"] = "TASK-002"
    second["title"] = "Second task"
    second["checklist"] = [{"id": "ck-tests", "text": "Existing", "done": False}]
    sample_item = {
        **sample_item,
        "checklist": [{"id": "ck-tests", "text": "Move me", "done": False}],
    }
    write_todos(
        git_project,
        [sample_item, {**second, "_file": "items/002.yaml"}],
    )
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    proposal = RestructuringProposal(
        item_id=item.id,
        checklist_moves=[
            ChecklistMove(id="ck-tests", to_item_id="TASK-002"),
        ],
    )
    with pytest.raises(RestructuringError, match="already exists on target"):
        apply_restructure_proposal(ws, item, proposal)
