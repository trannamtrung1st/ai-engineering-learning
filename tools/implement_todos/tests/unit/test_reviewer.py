"""Review decision validation tests."""

from __future__ import annotations

import pytest

from todos_tool.errors import ReviewError
from todos_tool.models import (
    ItemStatus,
    ItemType,
    TodoItem,
    ValidationCommandResult,
)
from todos_tool.reviewer import accept_decision, parse_review_decision


def _item() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        status=ItemStatus.IN_PROGRESS,
        description="desc",
        acceptance_criteria=["Crit A", "Crit B"],
        validation={"commands": ["pytest"]},
    )


VALID_PASS = """
Here is my decision:
```json
{
  "schema_version": 1,
  "item_id": "TASK-001",
  "logical_attempt": 1,
  "decision": "pass",
  "summary": "Looks good",
  "acceptance_criteria": [
    {"criterion": "Crit A", "passed": true, "evidence": "ok"},
    {"criterion": "Crit B", "passed": true, "evidence": "ok"}
  ],
  "validation": [
    {"command": "pytest", "passed": true, "exit_code": 0, "summary": "ok"}
  ],
  "instruction_compliance": {"passed": true, "violations": []},
  "issues": [],
  "recommended_next_action": "mark_done"
}
```
"""


def test_parse_and_accept_pass() -> None:
    decision = parse_review_decision(VALID_PASS)
    accept_decision(decision, _item(), 1)


def test_accepts_matching_authoritative_validation() -> None:
    decision = parse_review_decision(VALID_PASS)
    authoritative = [
        ValidationCommandResult(
            command="pytest",
            passed=True,
            exit_code=0,
            summary="runner output",
        )
    ]
    accept_decision(decision, _item(), 1, authoritative)


def test_rejects_claim_that_contradicts_authoritative_validation() -> None:
    decision = parse_review_decision(VALID_PASS)
    authoritative = [
        ValidationCommandResult(
            command="pytest",
            passed=False,
            exit_code=1,
            summary="failed",
        )
    ]
    with pytest.raises(ReviewError, match="contradict"):
        accept_decision(decision, _item(), 1, authoritative)


def test_reject_stale_attempt() -> None:
    decision = parse_review_decision(VALID_PASS)
    with pytest.raises(ReviewError):
        accept_decision(decision, _item(), 2)


def test_reject_failed_criterion_as_pass() -> None:
    text = VALID_PASS.replace('"passed": true, "evidence": "ok"\n    },\n    {"criterion": "Crit B"',
                              '"passed": false, "evidence": "no"\n    },\n    {"criterion": "Crit B"')
    # Simpler: craft fail on Crit A
    bad = VALID_PASS.replace(
        '{"criterion": "Crit A", "passed": true, "evidence": "ok"}',
        '{"criterion": "Crit A", "passed": false, "evidence": "no"}',
    )
    decision = parse_review_decision(bad)
    with pytest.raises(ReviewError):
        accept_decision(decision, _item(), 1)


def test_missing_json_raises() -> None:
    with pytest.raises(ReviewError):
        parse_review_decision("all done and passed, ship it")


def test_accept_pass_with_structured_info_issues() -> None:
    text = """
```json
{
  "schema_version": 1,
  "item_id": "TASK-001",
  "logical_attempt": 1,
  "decision": "pass",
  "summary": "Looks good",
  "acceptance_criteria": [
    {"criterion": "Crit A", "passed": true, "evidence": "ok"},
    {"criterion": "Crit B", "passed": true, "evidence": "ok"}
  ],
  "validation": [
    {"command": "pytest", "passed": true, "exit_code": 0, "summary": "ok"}
  ],
  "instruction_compliance": {"passed": true, "violations": []},
  "issues": [
    {
      "severity": "info",
      "title": "npm run test exits 1 until UT-002",
      "detail": "Expected interim behavior."
    }
  ],
  "recommended_next_action": "mark_done"
}
```
"""
    decision = parse_review_decision(text)
    accept_decision(decision, _item(), 1)
    assert decision.issue_strings() == [
        "[info] npm run test exits 1 until UT-002: Expected interim behavior."
    ]


def test_accept_pass_with_structured_low_issues() -> None:
    text = VALID_PASS.replace(
        '"issues": []',
        '"issues": [{"severity": "low", "title": "Consider renaming helper", "detail": "Optional cleanup."}]',
    )
    decision = parse_review_decision(text)
    accept_decision(decision, _item(), 1)
    assert decision.issue_strings() == [
        "[low] Consider renaming helper: Optional cleanup."
    ]


def test_reject_pass_with_structured_blocking_issue() -> None:
    text = VALID_PASS.replace(
        '"issues": []',
        '"issues": [{"severity": "high", "title": "Missing tests", "detail": "blocker"}]',
    )
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="blocking issues"):
        accept_decision(decision, _item(), 1)


def test_reject_pass_with_legacy_string_issue() -> None:
    text = VALID_PASS.replace('"issues": []', '"issues": ["needs follow-up"]')
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="blocking issues"):
        accept_decision(decision, _item(), 1)


def test_reject_substituted_acceptance_criterion() -> None:
    text = VALID_PASS.replace('"Crit A"', '"Crit A renamed"')
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="exact acceptance criteria"):
        accept_decision(decision, _item(), 1)


def test_reject_duplicate_acceptance_criterion() -> None:
    text = VALID_PASS.replace(
        '"acceptance_criteria": [',
        '"acceptance_criteria": [\n'
        '    {"criterion": "Crit A", "passed": true, "evidence": "dup"},',
    )
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="Duplicate acceptance criterion"):
        accept_decision(decision, _item(), 1)


def test_reject_omitted_validation_command() -> None:
    text = VALID_PASS.replace(
        '"validation": [\n    {"command": "pytest", "passed": true, "exit_code": 0, "summary": "ok"}\n  ],',
        '"validation": [],',
    )
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="validation results"):
        accept_decision(decision, _item(), 1)


def test_reject_failed_validation_command() -> None:
    text = VALID_PASS.replace(
        '"passed": true, "exit_code": 0, "summary": "ok"',
        '"passed": false, "exit_code": 1, "summary": "failed"',
    )
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="mandatory validation"):
        accept_decision(decision, _item(), 1)


def test_reject_unexpected_validation_command() -> None:
    text = VALID_PASS.replace(
        '"command": "pytest"',
        '"command": "npm test"',
    )
    decision = parse_review_decision(text)
    with pytest.raises(ReviewError, match="validation command"):
        accept_decision(decision, _item(), 1)
