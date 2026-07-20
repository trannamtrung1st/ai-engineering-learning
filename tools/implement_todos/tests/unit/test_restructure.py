"""Controlled restructuring validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.continuation import apply_restructure_proposal, load_restructure_proposal
from todos_tool.errors import RestructuringError
from todos_tool.manifest import load_workspace
from todos_tool.models import ItemStatus, RestructuringProposal


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
