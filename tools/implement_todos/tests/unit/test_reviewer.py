"""Review decision validation tests."""

from __future__ import annotations

import pytest

from todos_tool.errors import ReviewError
from todos_tool.models import (
    EvidenceCommandResult,
    ItemStatus,
    ItemType,
    ReviewDecision,
    TodoItem,
    ValidationCommandResult,
)
from todos_tool.reviewer import accept_decision


def _item() -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        status=ItemStatus.IN_PROGRESS,
        description="desc",
        acceptance_criteria=["Crit A", "Crit B"],
        validation={"commands": []},
    )


def _authoritative() -> list[ValidationCommandResult]:
    return [
        ValidationCommandResult(
            command="pytest",
            passed=True,
            exit_code=0,
            summary="runner output",
        )
    ]


VALID_PASS_DATA: dict = {
    "schema_version": 1,
    "item_id": "TASK-001",
    "logical_attempt": 1,
    "decision": "pass",
    "summary": "Looks good",
    "acceptance_criteria": [
        {"criterion": "Crit A", "passed": True, "evidence": "ok"},
        {"criterion": "Crit B", "passed": True, "evidence": "ok"},
    ],
    "validation": [
        {"command": "pytest", "passed": True, "exit_code": 0, "summary": "ok"}
    ],
    "instruction_compliance": {"passed": True, "violations": []},
    "issues": [],
    "proposed_commit_message": "agent: feat: add greeting helper",
    "recommended_next_action": "mark_done",
}


def _decision(data: dict | None = None) -> ReviewDecision:
    payload = dict(VALID_PASS_DATA)
    if data:
        payload.update(data)
    return ReviewDecision.model_validate(payload)


def test_parse_and_accept_pass() -> None:
    decision = _decision()
    accept_decision(decision, _item(), 1, _authoritative())


def test_accepts_matching_authoritative_validation() -> None:
    decision = _decision()
    accept_decision(decision, _item(), 1, _authoritative())


def test_rejects_claim_that_contradicts_authoritative_validation() -> None:
    decision = _decision()
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
    decision = _decision()
    with pytest.raises(ReviewError):
        accept_decision(decision, _item(), 2, _authoritative())


def test_reject_failed_criterion_as_pass() -> None:
    decision = _decision(
        {
            "acceptance_criteria": [
                {"criterion": "Crit A", "passed": False, "evidence": "no"},
                {"criterion": "Crit B", "passed": True, "evidence": "ok"},
            ]
        }
    )
    with pytest.raises(ReviewError):
        accept_decision(decision, _item(), 1, _authoritative())


def test_accept_pass_with_structured_info_issues() -> None:
    decision = _decision(
        {
            "issues": [
                {
                    "severity": "info",
                    "title": "npm run test exits 1 until UT-002",
                    "detail": "Expected interim behavior.",
                }
            ]
        }
    )
    accept_decision(decision, _item(), 1, _authoritative())
    assert decision.issue_strings() == [
        "[info] npm run test exits 1 until UT-002: Expected interim behavior."
    ]


def test_accept_pass_with_structured_low_issues() -> None:
    decision = _decision(
        {
            "issues": [
                {
                    "severity": "low",
                    "title": "Consider renaming helper",
                    "detail": "Optional cleanup.",
                }
            ]
        }
    )
    accept_decision(decision, _item(), 1, _authoritative())
    assert decision.issue_strings() == [
        "[low] Consider renaming helper: Optional cleanup."
    ]


def test_reject_pass_with_structured_blocking_issue() -> None:
    decision = _decision(
        {
            "issues": [
                {
                    "severity": "high",
                    "title": "Missing tests",
                    "detail": "blocker",
                }
            ]
        }
    )
    with pytest.raises(ReviewError, match="blocking issues"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_reject_pass_with_legacy_string_issue() -> None:
    decision = _decision({"issues": ["needs follow-up"]})
    with pytest.raises(ReviewError, match="blocking issues"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_reject_pass_without_proposed_commit_message_when_commit_required() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        status=ItemStatus.IN_PROGRESS,
        description="desc",
        acceptance_criteria=["Crit A", "Crit B"],
        validation={"commands": []},
        allow_empty_commit=False,
    )
    decision = _decision({"proposed_commit_message": ""})
    with pytest.raises(ReviewError, match="proposed_commit_message"):
        accept_decision(decision, item, 1, _authoritative())


def test_accept_pass_without_proposed_commit_message_by_default() -> None:
    decision = _decision({"proposed_commit_message": ""})
    accept_decision(decision, _item(), 1, _authoritative())


def test_accept_multiplication_sign_variant_in_criterion() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        status=ItemStatus.IN_PROGRESS,
        description="desc",
        acceptance_criteria=["Overview renders at 1440×900."],
        validation={"commands": []},
    )
    decision = _decision(
        {
            "acceptance_criteria": [
                {
                    "criterion": "Overview renders at 1440x900.",
                    "passed": True,
                    "evidence": "ok",
                }
            ],
            "validation": [],
        }
    )
    accept_decision(decision, item, 1, [])


def test_reject_substituted_acceptance_criterion() -> None:
    decision = _decision(
        {
            "acceptance_criteria": [
                {"criterion": "Crit A renamed", "passed": True, "evidence": "ok"},
                {"criterion": "Crit B", "passed": True, "evidence": "ok"},
            ]
        }
    )
    with pytest.raises(ReviewError, match="exact acceptance criteria"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_reject_duplicate_acceptance_criterion() -> None:
    decision = _decision(
        {
            "acceptance_criteria": [
                {"criterion": "Crit A", "passed": True, "evidence": "dup"},
                {"criterion": "Crit A", "passed": True, "evidence": "dup"},
                {"criterion": "Crit B", "passed": True, "evidence": "ok"},
            ]
        }
    )
    with pytest.raises(ReviewError, match="Duplicate acceptance criterion"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_reject_omitted_validation_command() -> None:
    decision = _decision({"validation": []})
    with pytest.raises(ReviewError, match="validation results"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_reject_failed_validation_command() -> None:
    decision = _decision(
        {
            "validation": [
                {
                    "command": "pytest",
                    "passed": False,
                    "exit_code": 1,
                    "summary": "failed",
                }
            ]
        }
    )
    with pytest.raises(ReviewError, match="mandatory validation"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_reject_unexpected_validation_command() -> None:
    decision = _decision(
        {
            "validation": [
                {
                    "command": "npm test",
                    "passed": True,
                    "exit_code": 0,
                    "summary": "ok",
                }
            ]
        }
    )
    with pytest.raises(ReviewError, match="validation command"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_rejects_case_only_validation_command_drift() -> None:
    decision = _decision(
        {
            "validation": [
                {
                    "command": "PyTest",
                    "passed": True,
                    "exit_code": 0,
                    "summary": "ok",
                }
            ]
        }
    )
    with pytest.raises(ReviewError, match="validation command"):
        accept_decision(decision, _item(), 1, _authoritative())


def test_rejects_missing_completion_evidence() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Add greeting helper",
        type=ItemType.FEATURE,
        status=ItemStatus.IN_PROGRESS,
        description="desc",
        acceptance_criteria=["Crit A", "Crit B"],
        evidence={"commands": [{"command": "pytest"}]},
    )
    authoritative_evidence = [
        EvidenceCommandResult(
            command="pytest",
            cwd=".",
            passed=True,
            source="driver",
            exit_code=0,
        )
    ]
    decision = _decision()
    with pytest.raises(ReviewError, match="completion evidence"):
        accept_decision(
            decision,
            item,
            1,
            _authoritative(),
            authoritative_evidence,
        )
