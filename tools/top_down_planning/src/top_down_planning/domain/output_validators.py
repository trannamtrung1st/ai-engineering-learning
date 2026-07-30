"""Deterministic output validation (proposal §12.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from top_down_planning.domain.models import Plan
from top_down_planning.domain.production import validate_production_checks
from top_down_planning.domain.reviews import (
    blocking_unresolved_finding_ids_from_payload,
    find_whole_output_approval,
)
from top_down_planning.domain.validators import (
    ValidationIssue,
    ValidationResult,
    severity_for_validation_mode,
    validation_issue,
)

ValidationMode = Literal["draft", "approval"]


@dataclass
class OutputReviewState:
    """Optional whole-output review context for approval-mode hooks."""

    approved_output_revision: int | None = None
    unresolved_blocking_findings: list[str] = field(default_factory=list)


@dataclass
class OutputDigestBundle:
    """Optional digest bindings for output approval-mode hooks."""

    output_revision: int | None = None
    expected_output_digest: str | None = None
    actual_output_digest: str | None = None
    expected_plan_digest: str | None = None
    actual_plan_digest: str | None = None


def build_output_approval_validation_context(
    *,
    production: dict[str, Any],
    approval: dict[str, Any],
    actual_output_digest: str,
    actual_plan_digest: str,
) -> tuple[OutputReviewState, OutputDigestBundle]:
    approved_digests = approval.get("approved_digests")
    expected_digests: dict[str, str] = (
        {str(key): str(value) for key, value in approved_digests.items()}
        if isinstance(approved_digests, dict)
        else {}
    )
    review_state = OutputReviewState(
        approved_output_revision=int(approval["target_revision"]),
        unresolved_blocking_findings=blocking_unresolved_finding_ids_from_payload(
            approval
        ),
    )
    digest_bundle = OutputDigestBundle(
        output_revision=int(production["output_revision"]),
        expected_output_digest=expected_digests.get("output"),
        actual_output_digest=actual_output_digest,
        expected_plan_digest=expected_digests.get("plan"),
        actual_plan_digest=actual_plan_digest,
    )
    return review_state, digest_bundle


def validate_output_review_hooks(
    production: dict[str, Any],
    review_state: OutputReviewState,
    *,
    mode: ValidationMode = "draft",
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for finding in review_state.unresolved_blocking_findings:
        issues.append(
            validation_issue(
                "unresolved_blocking_finding",
                "error",
                f"blocking whole-output finding remains unresolved: {finding}",
                [finding],
            )
        )

    if review_state.approved_output_revision is not None:
        output_revision = int(production["output_revision"])
        if review_state.approved_output_revision != output_revision:
            issues.append(
                validation_issue(
                    "approval_revision_mismatch",
                    "error",
                    (
                        f"whole-output approval targets revision "
                        f"{review_state.approved_output_revision}, but current output "
                        f"revision is {output_revision}"
                    ),
                    ["production", "output_revision"],
                )
            )
    elif not review_state.unresolved_blocking_findings:
        issues.append(
            validation_issue(
                "review_state_not_checked",
                severity_for_validation_mode(mode, "warning"),
                "approved output revision was not provided for comparison",
                ["production", "output_revision"],
            )
        )

    return issues


def validate_output_digest_hooks(
    digests: OutputDigestBundle,
    *,
    mode: ValidationMode = "draft",
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if digests.output_revision is not None:
        if digests.expected_output_digest is None or digests.actual_output_digest is None:
            issues.append(
                validation_issue(
                    "digest_not_checked",
                    severity_for_validation_mode(mode, "warning"),
                    "output digest was not fully provided for comparison",
                    ["output"],
                )
            )
        elif digests.expected_output_digest != digests.actual_output_digest:
            issues.append(
                validation_issue(
                    "digest_mismatch",
                    "error",
                    "output digest does not match the reviewed version",
                    ["output"],
                )
            )

    if digests.expected_plan_digest is not None and digests.actual_plan_digest is not None:
        if digests.expected_plan_digest != digests.actual_plan_digest:
            issues.append(
                validation_issue(
                    "digest_mismatch",
                    "error",
                    "plan digest changed after whole-plan approval",
                    ["plan"],
                )
            )
    elif digests.actual_plan_digest is not None:
        issues.append(
            validation_issue(
                "digest_not_checked",
                severity_for_validation_mode(mode, "warning"),
                "plan digest was not fully provided for comparison",
                ["plan"],
            )
        )

    return issues


def validate_output(
    plan: Plan,
    production: dict[str, Any],
    *,
    review_state: OutputReviewState | None = None,
    digests: OutputDigestBundle | None = None,
    reviews: list[dict[str, Any]] | None = None,
    mode: ValidationMode = "draft",
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    for message in validate_production_checks(plan, production):
        issues.append(validation_issue("output_check_failed", "error", message))

    if mode == "approval":
        completion_claim = production.get("completion_claim")
        if not isinstance(completion_claim, dict):
            issues.append(
                validation_issue(
                    "completion_claim_missing",
                    "error",
                    "output approval requires a production completion claim",
                )
            )
        elif not str(completion_claim.get("goal_assessment") or "").strip():
            issues.append(
                validation_issue(
                    "goal_assessment_missing",
                    "error",
                    "completion claim is missing goal_assessment",
                )
            )

        if reviews is not None:
            output_revision = int(production["output_revision"])
            approval = find_whole_output_approval(reviews, output_revision)
            if approval is None:
                issues.append(
                    validation_issue(
                        "whole_output_review_not_approved",
                        "error",
                        (
                            "whole-output review is not approved for current "
                            f"output revision {output_revision}"
                        ),
                    )
                )

    if review_state is not None:
        issues.extend(validate_output_review_hooks(production, review_state, mode=mode))
    if digests is not None:
        issues.extend(validate_output_digest_hooks(digests, mode=mode))

    return ValidationResult(issues=issues)
