"""Neutral prompt rendering tests."""

from __future__ import annotations

from todos_tool.models import ItemType, TodoItem
from todos_tool.profile_loader import ResolvedContextFile
from todos_tool.project_context import ContextFileRef, ProjectContext
from todos_tool.prompts import (
    build_repair_prompt,
    build_review_prompt,
    build_work_prompt,
    prompt_requires_instruction_discovery,
)


def _item() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add helper",
        type=ItemType.FEATURE,
        description="Implement helper.",
        acceptance_criteria=["Helper exists."],
    )


def test_work_prompt_has_no_project_specific_defaults() -> None:
    prompt = build_work_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=[],
        todos_dir="todos",
    )
    assert "AGENTS.md" not in prompt
    assert "CONTRIBUTING.md" not in prompt
    assert prompt_requires_instruction_discovery(prompt)


def test_review_prompt_uses_submission_tool() -> None:
    prompt = build_review_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=["pytest"],
        work_summary="done",
        git_diff="(none)",
        git_status="(clean)",
        commit_hint="Use `agent: feat:` for features.",
    )
    assert "Do NOT rerun validation commands" in prompt
    assert "todos-review-tool submit --json" in prompt
    assert "do **not** return JSON in chat" in prompt
    assert "Submit your decision only through the review submission CLI" in prompt
    assert "Commit subject guidance" in prompt
    assert "proposed_commit_message" in prompt


def test_prompts_include_supplied_context_only() -> None:
    ctx = ProjectContext.neutral().with_extra_context_files(
        (ContextFileRef(path="docs/guide.md", required=False),)
    )
    resolved = [
        ResolvedContextFile(path="docs/guide.md", required=False, exists=True),
    ]
    prompt = build_work_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=[],
        project_context=ctx,
        resolved_context_files=resolved,
    )
    assert "docs/guide.md" in prompt
    assert "Repository context" in prompt


def test_repair_prompt_includes_diagnostic_and_contract() -> None:
    prompt = build_repair_prompt(
        diagnostic="manifest.yaml: invalid field",
        todos_dir="todos",
        yaml_files=["todos/manifest.yaml"],
    )
    assert "manifest.yaml: invalid field" in prompt
    assert "Do not change files outside the TODO YAML set" in prompt
