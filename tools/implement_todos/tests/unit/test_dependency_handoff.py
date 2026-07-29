"""Durable dependency handoff between TODOs."""

from __future__ import annotations

import json
import os

import pytest

from todos_tool.implementation_state import (
    dependency_handoff_for_item,
    load_workspace_run_state,
)
from todos_tool.orchestrator import Orchestrator
from todos_tool.run_config import RunConfig
from todos_tool.prompts import build_work_prompt
from tests.helpers import write_todos


@pytest.mark.asyncio
async def test_completion_handoff_recorded_for_dependents(
    git_project,
    fake_agent,
    sample_item,
) -> None:
    item_a = dict(sample_item)
    item_b = {
        **sample_item,
        "id": "TASK-002",
        "title": "Depends on first",
        "depends_on": ["TASK-001"],
        "_file": "items/002.yaml",
    }
    write_todos(git_project, [item_a, item_b], settings={"auto_commit": False})
    os.environ["FAKE_AGENT_WORKSPACE"] = str(git_project)
    os.environ["FAKE_AGENT_DECISION"] = "pass"
    config = RunConfig(
        workspace_root=git_project,
        agent_bin=str(fake_agent),
        skip_probe=True,
        auto_commit=False,
    )
    orch = Orchestrator(config)
    report = await orch.run()
    assert report.completed == ["TASK-001", "TASK-002"]
    runs_root = git_project / "todos/runs"
    ws_state = load_workspace_run_state(runs_root)
    assert "TASK-001" in ws_state.dependency_outputs
    outputs = dependency_handoff_for_item(runs_root, ["TASK-001"])
    assert outputs and outputs[0].item_id == "TASK-001"
    completion_path = (
        runs_root / "TASK-001/attempts/01/completion-report.json"
    )
    assert completion_path.is_file()
    payload = json.loads(completion_path.read_text(encoding="utf-8"))
    assert payload["item_id"] == "TASK-001"


def test_dependency_handoff_rendered_in_work_prompt(sample_item) -> None:
    from todos_tool.implementation_state import DependencyOutput
    from todos_tool.models import TodoItem

    item = TodoItem.from_dict(sample_item)
    prompt = build_work_prompt(
        item,
        logical_attempt=1,
        resolved_commands=[],
        dependency_outputs=[
            DependencyOutput(
                item_id="TASK-000",
                summary="Prior work done",
                commit_sha="abc123",
                changed_paths=["src/foo.py"],
            )
        ],
    )
    assert "Dependency completion handoff" in prompt
    assert "TASK-000" in prompt
    assert "src/foo.py" in prompt
