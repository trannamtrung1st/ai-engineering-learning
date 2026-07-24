"""Neutral prompt rendering tests."""

from __future__ import annotations

from todos_tool.models import ChecklistItem, ItemType, TodoItem
from todos_tool.project_context import ContextFileRef, ProjectContext, ResolvedContextFile
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
    assert "## Artifact reporting" in prompt
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
    assert "todos-review-tool scaffold" in prompt
    assert "todos-review-tool validate --json" in prompt
    assert "todos-review-tool submit --json" in prompt
    assert "do **not** return JSON in chat" in prompt
    assert "Submit your decision only through the review submission CLI" in prompt
    assert "Commit subject guidance" in prompt
    assert "proposed_commit_message" in prompt
    assert "Glob/Grep skip gitignored paths" in prompt


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


def _item_with_checklist() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add helper",
        type=ItemType.FEATURE,
        description="Implement helper.",
        acceptance_criteria=["Helper exists."],
        checklist=[
            ChecklistItem(id="ck-a", text="Implement helper", done=False),
            ChecklistItem(id="ck-b", text="Add tests", done=True),
        ],
    )


def test_work_prompt_includes_checklist_work_plan() -> None:
    item = _item_with_checklist()
    prompt = build_work_prompt(
        item,
        logical_attempt=1,
        resolved_commands=[],
    )
    assert "## Checklist work plan" in prompt
    assert "`ck-a`: Implement helper" in prompt
    assert "checklist_moves" in prompt
    assert "Do NOT mark the item complete" in prompt


def test_review_prompt_includes_visual_rules_when_artifacts_listed() -> None:
    summary = """
## Artifacts
- ai-harness/generated/runs/screenshots/slice/overview.png
"""
    prompt = build_review_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=["pytest"],
        work_summary=summary,
        git_diff="(none)",
        git_status="(clean)",
    )
    assert "## Visual evidence rules" in prompt
    assert "overview.png" in prompt


def test_review_prompt_includes_checklist_compliance_rules() -> None:
    item = _item_with_checklist()
    prompt = build_review_prompt(
        item,
        logical_attempt=1,
        resolved_commands=["pytest"],
        work_summary="done",
        git_diff="(none)",
        git_status="(clean)",
    )
    assert "## Checklist review" in prompt
    assert "instruction_compliance.passed=false" in prompt
    assert "`ck-a`: Implement helper" in prompt
    assert "Open checklist entries: `ck-a`" in prompt
