"""Outcome resolution and acceptance invariant (proposal §15, §21)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from top_down_planning.domain.models import Plan, PlanningLimits
from top_down_planning.domain.production import (
    all_applicable_items_processed,
    completion_claim_asserts_goal_met,
)
from top_down_planning.domain.reviews import (
    required_unresolved_finding_ids_from_payload,
    find_whole_output_approval,
    find_whole_plan_approval,
)
from top_down_planning.domain.output_validators import (
    OutputDigestBundle,
    OutputReviewState,
    build_output_approval_validation_context,
    validate_output,
)
from top_down_planning.domain.validators import (
    DigestBundle,
    ReviewState,
    ValidationResult,
    build_plan_approval_validation_context,
    validate_plan,
)

QualityOutcome = Literal["accepted", "rejected", "blocked"]


@dataclass(frozen=True)
class AcceptanceInvariant:
    plan_whole_plan_review_approved_current_revision: bool
    plan_deterministic_plan_validation_passed: bool
    production_all_applicable_items_terminal_or_derived: bool
    production_output_goal_explicitly_assessed_as_met: bool
    output_whole_output_review_approved_current_revision: bool
    output_deterministic_output_validation_passed: bool
    findings_unresolved_required_findings: int

    @property
    def satisfied(self) -> bool:
        return (
            self.plan_whole_plan_review_approved_current_revision
            and self.plan_deterministic_plan_validation_passed
            and self.production_all_applicable_items_terminal_or_derived
            and self.production_output_goal_explicitly_assessed_as_met
            and self.output_whole_output_review_approved_current_revision
            and self.output_deterministic_output_validation_passed
            and self.findings_unresolved_required_findings == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan.whole_plan_review_approved_current_revision": (
                self.plan_whole_plan_review_approved_current_revision
            ),
            "plan.deterministic_plan_validation_passed": (
                self.plan_deterministic_plan_validation_passed
            ),
            "production.all_applicable_items_terminal_or_derived": (
                self.production_all_applicable_items_terminal_or_derived
            ),
            "production.output_goal_explicitly_assessed_as_met": (
                self.production_output_goal_explicitly_assessed_as_met
            ),
            "output.whole_output_review_approved_current_revision": (
                self.output_whole_output_review_approved_current_revision
            ),
            "output.deterministic_output_validation_passed": (
                self.output_deterministic_output_validation_passed
            ),
            "findings.unresolved_required_findings": (
                self.findings_unresolved_required_findings
            ),
        }


def evaluate_acceptance_invariant(
    *,
    plan: Plan,
    production: dict[str, Any],
    reviews: list[dict[str, Any]],
    limits: PlanningLimits,
    plan_approval: dict[str, Any] | None,
    output_approval: dict[str, Any] | None,
    actual_plan_digest: str,
    actual_config_contract_digest: str,
    actual_output_digest: str,
    actual_input_digest: str,
    actual_output_goal_digest: str,
    actual_context_spec_digest: str | None = None,
    actual_context_snapshot_digest: str | None = None,
) -> tuple[AcceptanceInvariant, ValidationResult, ValidationResult]:
    plan_review_state: ReviewState | None = None
    plan_digest_bundle: DigestBundle | None = None
    if plan_approval is not None:
        plan_review_state, plan_digest_bundle = build_plan_approval_validation_context(
            plan=plan,
            approval=plan_approval,
            actual_plan_digest=actual_plan_digest,
            actual_config_contract_digest=actual_config_contract_digest,
            actual_input_digest=actual_input_digest,
            actual_output_goal_digest=actual_output_goal_digest,
            actual_context_spec_digest=actual_context_spec_digest,
        )

    dispositions = dict(production.get("dispositions") or {})

    plan_validation = validate_plan(
        plan,
        limits=limits,
        review_state=plan_review_state,
        digests=plan_digest_bundle,
        dispositions=dispositions,
        reviews=reviews,
        mode="approval",
    )

    output_review_state: OutputReviewState | None = None
    output_digest_bundle: OutputDigestBundle | None = None
    if output_approval is not None:
        output_review_state, output_digest_bundle = build_output_approval_validation_context(
            production=production,
            approval=output_approval,
            actual_output_digest=actual_output_digest,
            actual_plan_digest=actual_plan_digest,
            actual_config_contract_digest=actual_config_contract_digest,
            actual_input_digest=actual_input_digest,
            actual_output_goal_digest=actual_output_goal_digest,
            actual_context_spec_digest=actual_context_spec_digest,
            actual_context_snapshot_digest=actual_context_snapshot_digest,
        )

    output_validation = validate_output(
        plan,
        production,
        review_state=output_review_state,
        digests=output_digest_bundle,
        reviews=reviews,
        mode="approval",
    )

    completion_claim = production.get("completion_claim")
    goal_assessed = completion_claim_asserts_goal_met(
        completion_claim if isinstance(completion_claim, dict) else None
    )

    unresolved_findings = 0
    if output_approval is not None:
        unresolved_findings = len(
            required_unresolved_finding_ids_from_payload(output_approval)
        )

    dispositions = dict(production.get("dispositions") or {})
    all_items_processed = all_applicable_items_processed(plan, dispositions)

    invariant = AcceptanceInvariant(
        plan_whole_plan_review_approved_current_revision=plan_approval is not None,
        plan_deterministic_plan_validation_passed=plan_validation.ok,
        production_all_applicable_items_terminal_or_derived=all_items_processed,
        production_output_goal_explicitly_assessed_as_met=goal_assessed,
        output_whole_output_review_approved_current_revision=output_approval is not None,
        output_deterministic_output_validation_passed=output_validation.ok,
        findings_unresolved_required_findings=unresolved_findings,
    )
    return invariant, plan_validation, output_validation


def resolve_quality_outcome(invariant: AcceptanceInvariant) -> QualityOutcome:
    if invariant.satisfied:
        return "accepted"
    if (
        not invariant.plan_deterministic_plan_validation_passed
        or not invariant.output_deterministic_output_validation_passed
        or not invariant.plan_whole_plan_review_approved_current_revision
        or not invariant.output_whole_output_review_approved_current_revision
    ):
        return "blocked"
    return "rejected"


def load_approvals_for_acceptance(
    reviews: list[dict[str, Any]],
    *,
    plan_revision: int,
    output_revision: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return (
        find_whole_plan_approval(reviews, plan_revision),
        find_whole_output_approval(reviews, output_revision),
    )
