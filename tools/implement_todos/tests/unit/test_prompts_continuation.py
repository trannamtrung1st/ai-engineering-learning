"""Prompt requirements and continuation bounds."""

from __future__ import annotations

from pathlib import Path

from todos_tool.continuation import build_continuation_context
from todos_tool.models import ItemType, TodoItem, ValidationCommandResult
from todos_tool.prompts import (
    build_review_prompt,
    build_work_prompt,
    prompt_requires_instruction_discovery,
)


def _item() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        description="Implement greeting.",
        acceptance_criteria=["Returns a greeting."],
        validation={"commands": ["pytest"]},
    )


def test_work_prompt_requires_instruction_discovery() -> None:
    prompt = build_work_prompt(
        _item(),
        logical_attempt=1,
        resolved_commands=["pytest"],
    )
    assert prompt_requires_instruction_discovery(prompt)
    assert "Do NOT commit" in prompt
    assert "Do NOT run the full authoritative check suite" in prompt


def test_review_prompt_requires_submission_tool() -> None:
    prompt = build_review_prompt(
        _item(),
        logical_attempt=2,
        resolved_commands=["pytest"],
        work_summary="did stuff",
        git_diff="diff --git a/x b/x",
        git_status=" M x",
        authoritative_validation=[
            ValidationCommandResult(
                command="pytest",
                passed=True,
                exit_code=0,
                summary="ok",
            )
        ],
    )
    assert "Submit your decision only through the review submission CLI" in prompt
    assert "todos-review-tool submit --json" in prompt
    assert "todos-tool schema show review-decision" in prompt
    assert "todos-tool example show review-decision" in prompt
    assert "TASK-001" in prompt
    assert "no unresolved blocking issue exists" in prompt
    assert "info/low (non-blocking on pass)" in prompt
    assert "Plain-string issues are treated as blocking" in prompt
    assert "Do NOT rerun validation commands" in prompt
    assert "except the review submission CLI" in prompt


def test_continuation_is_bounded(git_project: Path) -> None:
    huge = "x" * 50_000
    (git_project / "big.txt").write_text(huge, encoding="utf-8")
    ctx = build_continuation_context(
        item=_item(),
        logical_attempt=1,
        phase="work",
        workspace_root=git_project,
        previous_summary="y" * 10_000,
        failure_reason="timeout",
    )
    assert len(ctx) < 30_000
    assert "truncated" in ctx
    assert "Do not commit" in ctx or "do not commit" in ctx.lower()
