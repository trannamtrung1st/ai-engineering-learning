"""Validate structured review decisions loaded from session artifacts."""

from __future__ import annotations

from todos_tool.errors import ReviewError
from todos_tool.evidence_matcher import normalize_command, normalize_cwd
from todos_tool.models import (
    EvidenceCommandResult,
    ReviewDecision,
    TodoItem,
    ValidationCommandResult,
)


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split()).lower()


def _normalize_validation_command(command: str) -> str:
    return normalize_command(command)


def _normalize_evidence_key(command: str, cwd: str) -> str:
    return f"{normalize_command(command)}@{normalize_cwd(cwd)}"


def _validate_acceptance_coverage(
    decision: ReviewDecision,
    item: TodoItem,
) -> None:
    expected = {_normalize_text(criterion) for criterion in item.acceptance_criteria}
    reported: dict[str, str] = {}
    for entry in decision.acceptance_criteria:
        key = _normalize_text(entry.criterion)
        if key in reported:
            raise ReviewError(
                f"Duplicate acceptance criterion reported: {entry.criterion}"
            )
        reported[key] = entry.criterion

    missing = expected - set(reported)
    unexpected = set(reported) - expected
    if missing or unexpected:
        parts: list[str] = []
        if missing:
            parts.append(f"missing: {', '.join(sorted(missing))}")
        if unexpected:
            parts.append(f"unexpected: {', '.join(sorted(unexpected))}")
        raise ReviewError(
            "Pass requires exact acceptance criteria coverage "
            f"({'; '.join(parts)})"
        )

    if not all(entry.passed for entry in decision.acceptance_criteria):
        raise ReviewError("Pass requires every acceptance criterion to pass")


def _validate_command_coverage(
    decision: ReviewDecision,
    authoritative_validation: list[ValidationCommandResult],
) -> None:
    expected = {
        _normalize_validation_command(result.command)
        for result in authoritative_validation
    }
    if not expected:
        return

    if not decision.validation:
        raise ReviewError("Pass requires validation results for mandatory commands")

    reported: dict[str, str] = {}
    for entry in decision.validation:
        key = _normalize_validation_command(entry.command)
        if key in reported:
            raise ReviewError(f"Duplicate validation command reported: {entry.command}")
        reported[key] = entry.command

    missing = expected - set(reported)
    unexpected = set(reported) - expected
    if missing or unexpected:
        parts: list[str] = []
        if missing:
            parts.append(f"missing: {', '.join(sorted(missing))}")
        if unexpected:
            parts.append(f"unexpected: {', '.join(sorted(unexpected))}")
        raise ReviewError(
            "Pass requires every configured validation command to be reported "
            f"({'; '.join(parts)})"
        )

    if not all(entry.passed for entry in decision.validation):
        raise ReviewError("Pass requires all mandatory validation to pass")


def _validate_authoritative_validation(
    decision: ReviewDecision,
    authoritative: list[ValidationCommandResult],
) -> None:
    expected = {
        _normalize_validation_command(result.command): result
        for result in authoritative
    }
    reported = {
        _normalize_validation_command(result.command): result
        for result in decision.validation
    }
    if set(reported) != set(expected):
        raise ReviewError(
            "Review validation commands do not match authoritative results"
        )

    disagreements: list[str] = []
    for key, actual in expected.items():
        claimed = reported[key]
        if (
            claimed.passed != actual.passed
            or claimed.exit_code != actual.exit_code
        ):
            disagreements.append(actual.command)
    if disagreements:
        raise ReviewError(
            "Review validation results contradict authoritative execution: "
            + ", ".join(disagreements)
        )
    if not all(result.passed for result in authoritative):
        raise ReviewError("Pass rejected because authoritative validation failed")


def _validate_evidence_coverage(
    decision: ReviewDecision,
    authoritative_evidence: list[EvidenceCommandResult],
) -> None:
    expected = {
        _normalize_evidence_key(result.command, result.cwd)
        for result in authoritative_evidence
    }
    if not expected:
        return

    if not decision.evidence:
        raise ReviewError("Pass requires completion evidence results for mandatory commands")

    reported: dict[str, str] = {}
    for entry in decision.evidence:
        key = _normalize_evidence_key(entry.command, entry.cwd)
        if key in reported:
            raise ReviewError(
                f"Duplicate completion evidence command reported: {entry.command}"
            )
        reported[key] = entry.command

    missing = expected - set(reported)
    unexpected = set(reported) - expected
    if missing or unexpected:
        parts: list[str] = []
        if missing:
            parts.append(f"missing: {', '.join(sorted(missing))}")
        if unexpected:
            parts.append(f"unexpected: {', '.join(sorted(unexpected))}")
        raise ReviewError(
            "Pass requires every configured completion evidence command to be reported "
            f"({'; '.join(parts)})"
        )

    if not all(entry.passed for entry in decision.evidence):
        raise ReviewError("Pass requires all mandatory completion evidence to pass")


def _validate_authoritative_evidence(
    decision: ReviewDecision,
    authoritative: list[EvidenceCommandResult],
) -> None:
    expected = {
        _normalize_evidence_key(result.command, result.cwd): result
        for result in authoritative
    }
    reported = {
        _normalize_evidence_key(result.command, result.cwd): result
        for result in decision.evidence
    }
    if set(reported) != set(expected):
        raise ReviewError(
            "Review completion evidence commands do not match authoritative results"
        )

    disagreements: list[str] = []
    for key, actual in expected.items():
        claimed = reported[key]
        if (
            claimed.passed != actual.passed
            or claimed.exit_code != actual.exit_code
        ):
            disagreements.append(f"{actual.command}@{actual.cwd}")
    if disagreements:
        raise ReviewError(
            "Review completion evidence contradict authoritative execution: "
            + ", ".join(disagreements)
        )
    if not all(result.passed for result in authoritative):
        raise ReviewError("Pass rejected because authoritative completion evidence failed")


def validate_pass(
    decision: ReviewDecision,
    item: TodoItem,
    logical_attempt: int,
    authoritative_validation: list[ValidationCommandResult],
    authoritative_evidence: list[EvidenceCommandResult] | None = None,
) -> None:
    """Raise ReviewError if a claimed pass is not actually valid."""
    if decision.item_id != item.id:
        raise ReviewError(
            f"Review item_id mismatch: got {decision.item_id}, expected {item.id}"
        )
    if decision.logical_attempt != logical_attempt:
        raise ReviewError(
            f"Review logical_attempt mismatch: got {decision.logical_attempt}, "
            f"expected {logical_attempt}"
        )

    if decision.decision != "pass":
        return

    if not decision.acceptance_criteria:
        raise ReviewError("Pass requires acceptance_criteria results")

    _validate_acceptance_coverage(decision, item)
    _validate_command_coverage(decision, authoritative_validation)
    _validate_authoritative_validation(decision, authoritative_validation)
    evidence = authoritative_evidence or []
    _validate_evidence_coverage(decision, evidence)
    _validate_authoritative_evidence(decision, evidence)

    if not decision.instruction_compliance.passed:
        raise ReviewError("Pass requires instruction_compliance.passed=true")

    blocking = [issue.display() for issue in decision.issues if issue.is_blocking]
    if blocking:
        raise ReviewError(
            "Pass cannot have unresolved blocking issues: "
            + "; ".join(blocking)
        )

    if decision.recommended_next_action != "mark_done":
        raise ReviewError("Pass requires recommended_next_action=mark_done")

    proposed = (decision.proposed_commit_message or "").strip()
    if not proposed:
        raise ReviewError("Pass requires proposed_commit_message")


def accept_decision(
    decision: ReviewDecision,
    item: TodoItem,
    logical_attempt: int,
    authoritative_validation: list[ValidationCommandResult],
    authoritative_evidence: list[EvidenceCommandResult] | None = None,
) -> ReviewDecision:
    validate_pass(
        decision,
        item,
        logical_attempt,
        authoritative_validation,
        authoritative_evidence,
    )
    return decision
