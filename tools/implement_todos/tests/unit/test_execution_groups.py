"""Atomic execution group scheduling."""

from __future__ import annotations

import pytest

from todos_tool.errors import SchedulingError
from todos_tool.manifest import load_workspace
from todos_tool.scheduler import next_execution_unit
from tests.helpers import write_todos


def test_execution_group_schedules_together(git_project, sample_item) -> None:
    item_a = dict(sample_item)
    item_b = {
        **sample_item,
        "id": "TASK-002",
        "title": "Paired task",
        "depends_on": [],
        "_file": "items/002.yaml",
    }
    todos = write_todos(git_project, [item_a, item_b])
    manifest_path = todos / "manifest.yaml"
    import yaml

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["execution_groups"] = [
        {
            "id": "pair",
            "members": ["TASK-001", "TASK-002"],
            "rationale": "inseparable surfaces",
        }
    ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    workspace = load_workspace(git_project)
    unit = next_execution_unit(workspace)
    assert unit.group_id == "pair"
    assert [item.id for item in unit.items] == ["TASK-001", "TASK-002"]


def test_duplicate_group_membership_rejected(git_project, sample_item) -> None:
    item_b = {
        **sample_item,
        "id": "TASK-002",
        "title": "Second",
        "_file": "items/002.yaml",
    }
    todos = write_todos(git_project, [sample_item, item_b])
    manifest_path = todos / "manifest.yaml"
    import yaml

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["execution_groups"] = [
        {"id": "g1", "members": ["TASK-001", "TASK-002"]},
        {"id": "g2", "members": ["TASK-002"]},
    ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    workspace = load_workspace(git_project)
    with pytest.raises(SchedulingError, match="multiple execution groups"):
        next_execution_unit(workspace)
