"""Consistency checks for bundled example agent_context configuration."""

from __future__ import annotations

from pathlib import Path

from todos_tool.agent_context import resolve_phase_agent_context, validate_agent_context_paths
from todos_tool.config_loader import build_run_config
from todos_tool.manifest import load_workspace
from todos_tool.prompts import build_review_prompt, build_work_prompt


def test_bundled_example_agent_context_merge_and_prompts() -> None:
    examples_root = Path(__file__).resolve().parents[2] / "examples"
    config = build_run_config(
        config_path=examples_root / "run.config.yaml",
        workspace=examples_root,
    )
    workspace = load_workspace(examples_root, config.todos_dir)
    item = workspace.get("TASK-001")
    assert item is not None

    implement = resolve_phase_agent_context(
        "implement",
        config.agent_context,
        workspace.manifest.agent_context,
        item.agent_context,
    )
    review = resolve_phase_agent_context(
        "review",
        config.agent_context,
        workspace.manifest.agent_context,
        item.agent_context,
    )
    validate_agent_context_paths(examples_root, implement, label="implement")
    validate_agent_context_paths(examples_root, review, label="review")

    work = build_work_prompt(
        item,
        logical_attempt=1,
        resolved_commands=[],
        agent_context=implement,
    )
    review_prompt = build_review_prompt(
        item,
        logical_attempt=1,
        resolved_commands=[],
        work_summary="summary",
        git_diff="",
        git_status="",
        agent_context=review,
    )

    assert "example-shared" in work
    assert "example-implement" in work
    assert "example-manifest-implement" in work
    assert "example-review" not in work
    assert "example-item-review" not in work
    assert "## Checklist work plan" in work
    assert "`ck-module`" in work

    assert "example-shared" in review_prompt
    assert "example-review" in review_prompt
    assert "example-item-review" in review_prompt
    assert "example-implement" not in review_prompt
    assert "example-manifest-implement" not in review_prompt
    assert "## Checklist review" in review_prompt
