"""Tests for review scaffold generation and validation."""

from __future__ import annotations

import pytest

from todos_tool.errors import ReviewError
from todos_tool.models import ItemType, TodoItem, ValidationCommandResult
from todos_tool.review_scaffold import (
    ReviewScaffold,
    build_review_scaffold,
    validate_review_decision,
)
from todos_tool.models import ReviewDecision


def _item() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Overview page",
        type=ItemType.FEATURE,
        description="Build overview.",
        acceptance_criteria=[
            "Overview renders at 1440×900.",
            "Decisions & Risks section links to docs/decisions.md.",
        ],
    )


def test_scaffold_template_uses_exact_criterion_strings() -> None:
    scaffold = build_review_scaffold(
        _item(),
        logical_attempt=1,
        authoritative_validation=[
            ValidationCommandResult(
                command="pytest",
                passed=True,
                exit_code=0,
                summary="ok",
            )
        ],
    )
    template = scaffold.decision_template()
    assert template["acceptance_criteria"][0]["criterion"] == "Overview renders at 1440×900."
    assert template["validation"][0]["command"] == "pytest"


def test_validate_accepts_multiplication_sign_variant() -> None:
    scaffold = build_review_scaffold(
        _item(),
        logical_attempt=1,
        authoritative_validation=[
            ValidationCommandResult(
                command="pytest",
                passed=True,
                exit_code=0,
                summary="ok",
            )
        ],
    )
    payload = scaffold.decision_template()
    payload["summary"] = "Looks good"
    payload["acceptance_criteria"][0]["criterion"] = "Overview renders at 1440x900."
    payload["acceptance_criteria"][0]["evidence"] = "verified screenshot"
    payload["acceptance_criteria"][1]["evidence"] = "link present"
    payload["proposed_commit_message"] = "agent: feat: overview"
    decision = ReviewDecision.model_validate(payload)
    validate_review_decision(scaffold, decision)


def test_validate_rejects_reworded_criterion() -> None:
    scaffold = build_review_scaffold(
        _item(),
        logical_attempt=1,
        authoritative_validation=[],
    )
    payload = scaffold.decision_template()
    payload["summary"] = "Looks good"
    payload["acceptance_criteria"][1]["criterion"] = "Decisions section links to decisions.md"
    payload["acceptance_criteria"][0]["evidence"] = "ok"
    payload["acceptance_criteria"][1]["evidence"] = "ok"
    decision = ReviewDecision.model_validate(payload)
    with pytest.raises(ReviewError, match="exact acceptance criteria"):
        validate_review_decision(scaffold, decision)
