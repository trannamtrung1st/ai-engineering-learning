"""Shared mandatory review stage transitions (proposal lifecycle)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from top_down_planning.domain.reviews import (
    ExhaustedReviewBudget,
    MandatoryReviewLimits,
    ReviewLoop,
    SCOPE_REVIEW_STAGE,
    allocate_discovery_finding_set_id,
    build_active_findings_view,
    required_unresolved_finding_ids,
    build_limit_reached_terminal,
    assert_mandatory_review_transition,
    is_scope_review_stage_name,
    loop_revise_at,
    mandatory_stage_respond_decision,
    next_finding_set_id,
    reviewer_package_policy_guidance,
)

ReviewArtifactKind = Literal["plan", "output"]

_INITIAL_STAGES = frozenset({None, "initial_review"})
_VERIFICATION_STAGES = frozenset({"finding_verification"})
_SCOPE_REVIEW_STAGES = frozenset({"scope_review"})


def is_scope_review_stage(loop: ReviewLoop) -> bool:
    return is_scope_review_stage_name(loop.active_stage)


def is_verification_or_initial_stage(loop: ReviewLoop) -> bool:
    return loop.active_stage in _INITIAL_STAGES | _VERIFICATION_STAGES


def seed_mandatory_loop_fields(loop: ReviewLoop) -> ReviewLoop:
    """Ensure a mandatory loop carries lifecycle defaults."""

    if loop.lifecycle_status is not None:
        return loop
    return replace(
        loop,
        lifecycle_status="review_pending",
        active_stage=None,
        finding_set_id=loop.finding_set_id,
        scope_review_rounds=loop.scope_review_rounds,
    )


def mark_findings_open(loop: ReviewLoop) -> ReviewLoop:
    """Enter Stage-1 after findings (or scope-review reopen) are raised."""

    current = loop.lifecycle_status or "review_pending"
    from_scope = is_scope_review_stage(loop)

    if from_scope:
        assert_mandatory_review_transition(current, "findings_open")
        finding_set_id = next_finding_set_id(loop)
        revision_cycles = 0
        target = "findings_open"
    elif current == "verification_pending":
        assert_mandatory_review_transition(current, "revision_in_progress")
        finding_set_id = loop.finding_set_id or next_finding_set_id(loop)
        revision_cycles = loop.revision_cycles
        target = "revision_in_progress"
    else:
        assert_mandatory_review_transition(current, "findings_open")
        finding_set_id = loop.finding_set_id or next_finding_set_id(loop)
        revision_cycles = loop.revision_cycles
        target = "findings_open"

    return replace(
        loop,
        lifecycle_status=target,  # type: ignore[arg-type]
        active_stage="finding_verification",
        finding_set_id=finding_set_id,
        revision_cycles=revision_cycles,
        approved_digests=None,
        scope_review_result=None,
    )


def mark_revision_in_progress(loop: ReviewLoop) -> ReviewLoop:
    current = loop.lifecycle_status or "findings_open"
    if current == "revision_in_progress":
        return replace(
            loop,
            lifecycle_status="revision_in_progress",
            active_stage="finding_verification",
            status="pending",
        )
    assert_mandatory_review_transition(current, "revision_in_progress")
    return replace(
        loop,
        lifecycle_status="revision_in_progress",
        active_stage="finding_verification",
        status="pending",
    )


def enter_planner_revision_cycle(loop: ReviewLoop) -> ReviewLoop:
    """Enter planner revision after needs_revision / changes_requested."""

    current = loop.lifecycle_status or "findings_open"
    if current == "revision_in_progress":
        return replace(
            loop,
            status="pending",
            active_stage="finding_verification",
        )
    return mark_revision_in_progress(loop)


def mandatory_orchestration_decision(loop: ReviewLoop) -> str:
    """Stage-native decision that drives mandatory review orchestration."""

    return mandatory_stage_respond_decision(loop)


def mark_verification_pending(loop: ReviewLoop, *, target_revision: int) -> ReviewLoop:
    current = loop.lifecycle_status or "revision_in_progress"
    assert_mandatory_review_transition(current, "verification_pending")
    return replace(
        loop,
        target_revision=target_revision,
        status="pending",
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        approved_digests=None,
    )


def mark_findings_closed(loop: ReviewLoop) -> ReviewLoop:
    current = loop.lifecycle_status or "verification_pending"
    assert_mandatory_review_transition(current, "findings_closed")
    return replace(
        loop,
        lifecycle_status="findings_closed",
        active_stage="finding_verification",
    )


def prepare_scope_review_loop(loop: ReviewLoop) -> ReviewLoop:
    """Reset for a fresh scope-complete review (approval gate).

    Clears reviewer session so the orchestrator allocates a new context.
    Does not frame the discovery pass with prior finding discussion; findings
    remain on the loop for audit only.

    When verification just closed (`verification_pending`), transitions through
    ``findings_closed`` here — the service does not set that lifecycle on respond.
    """

    current = loop.lifecycle_status or "review_pending"
    if current == "verification_pending":
        loop = mark_findings_closed(loop)
        current = loop.lifecycle_status or "findings_closed"
    assert_mandatory_review_transition(current, "scope_review_pending")

    prepared = replace(
        loop,
        status="pending",
        lifecycle_status="scope_review_pending",
        active_stage=SCOPE_REVIEW_STAGE,
        approved_digests=None,
        scope_review_result=None,
    )
    prepared, _finding_set_id = allocate_discovery_finding_set_id(prepared)
    return prepared.with_reviewer_session_released()


def mark_mandatory_approved(loop: ReviewLoop) -> ReviewLoop:
    if loop.lifecycle_status == "approved":
        return replace(
            loop,
            lifecycle_status="approved",
            status="approved",
            active_stage=SCOPE_REVIEW_STAGE,
        )
    current = loop.lifecycle_status or "scope_review_pending"
    assert_mandatory_review_transition(current, "approved")
    return replace(
        loop,
        lifecycle_status="approved",
        status="approved",
        active_stage=SCOPE_REVIEW_STAGE,
    )


def mark_limit_reached_loop(
    loop: ReviewLoop,
    *,
    limits: MandatoryReviewLimits,
    exhausted: ExhaustedReviewBudget,
) -> ReviewLoop:
    current = loop.lifecycle_status or "review_pending"
    assert_mandatory_review_transition(current, "limit_reached")
    terminal = build_limit_reached_terminal(
        exhausted_budget=exhausted,
        findings=loop.findings,
        limits=limits,
    )
    return replace(
        loop,
        status="blocked",
        lifecycle_status="limit_reached",
        findings=list(terminal.findings),
        exhausted_budget=terminal.exhausted_budget,
    )


def approved_means_final_approval(loop: ReviewLoop) -> bool:
    """True when ``approved`` may complete the mandatory gate (scope clear)."""

    return is_scope_review_stage(loop)


def approved_means_start_scope_review(loop: ReviewLoop) -> bool:
    """True when ``approved`` means findings closed / no findings → scope gate."""

    if is_scope_review_stage(loop):
        return False
    return not required_unresolved_finding_ids(
        loop.findings,
        revise_at=loop_revise_at(loop),
    )


def stage_package_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Fields embedded in reviewer packages for stage awareness."""

    from top_down_planning.domain.reviews import validate_review_stage

    stage = validate_review_stage(loop.active_stage) or "initial_review"
    fields: dict[str, Any] = {
        "stage": stage,
        "lifecycle_status": loop.lifecycle_status or "review_pending",
        "review_policy": reviewer_package_policy_guidance(),
    }
    if is_scope_review_stage_name(stage):
        # Freshness: omit prior finding lists from framing; include allocated id.
        if loop.finding_set_id is not None:
            fields["finding_set_id"] = loop.finding_set_id
        fields["freshness"] = {
            "omit_prior_finding_framing": True,
            "include_prior_findings": False,
            "purpose": (
                "Fresh scope review: report every material issue in the current "
                "scope without anchoring on prior finding discussion. Do not omit "
                "lower-severity issues because they may not force revision."
            ),
        }
        if loop.type == "whole_plan":
            fields["scope_review_guidance"] = [
                "internal consistency across titles, outcomes, acceptance criteria, and dependencies",
                "correctness of feasibility and verifiability claims",
                "contradictions and impossible or cyclic dependencies",
                "coverage of the original request",
                "required deliverables",
                "actionable completeness",
                "dependency and sequencing validity",
                "unresolved assumptions that prevent execution",
                "applicable planning acceptance criteria",
            ]
        elif loop.type == "whole_output":
            fields["scope_review_guidance"] = [
                "correctness against approved plan contracts and acceptance criteria",
                "consistency between evidence, dispositions, outputs, and completion claim",
                "material cross-output inconsistency",
                "conformance to the approved plan",
                "required deliverables",
                "missing required content",
                "broken references or dependencies",
                "regressions that prevent use or acceptance",
            ]
        else:
            raise ValueError(
                f"scope_review guidance is only defined for mandatory whole_* loops; "
                f"got {loop.type!r}"
            )
        fields["respond_contract"] = {
            "stage": SCOPE_REVIEW_STAGE,
            "required_fields": [
                "finding_set_id",
                "reported_findings",
                "review_completed",
                "target_digest",
                "scope_id",
                "summary",
            ],
            "optional_fields": ["acceptance_criteria_checked"],
        }
    elif stage == "finding_verification":
        if loop.finding_set_id is not None:
            fields["finding_set_id"] = loop.finding_set_id
        fields["verification_guidance"] = [
            "Verify disposition of prior findings",
            "Confirm required outcomes and evidence",
            "Check direct revision side effects only",
            "Do not perform a broad discovery pass",
        ]
        fields["respond_contract"] = {
            "stage": "finding_verification",
            "decisions": ["verified", "needs_revision", "blocked"],
            "required_fields": [
                "finding_results",
                "new_direct_side_effect_findings",
                "target_digest",
                "finding_set_id",
                "summary",
            ],
        }
    else:
        if loop.finding_set_id is not None:
            fields["finding_set_id"] = loop.finding_set_id
        fields["respond_contract"] = {
            "stage": "initial_review",
            "required_fields": [
                "finding_set_id",
                "reported_findings",
                "review_completed",
                "target_digest",
                "summary",
            ],
        }
        if loop.type == "whole_plan":
            fields["initial_review_guidance"] = [
                "Mandatory whole-plan gate: prioritize correctness and internal consistency",
                "Report contradictions, unverifiable claims, and overlapping executable scope",
                "Report every material issue with severity and category",
                "Clear initial discovery still requires a separate fresh scope review",
                "Do not treat this pass as final approval",
                "Echo finding_set_id unchanged; service derives lifecycle outcomes",
                "Do not omit lower-severity issues because they may not force revision",
            ]
        elif loop.type == "whole_output":
            fields["initial_review_guidance"] = [
                "Mandatory whole-output gate: prioritize correctness and cross-artifact consistency",
                "Report mismatches between evidence, dispositions, outputs, and plan contracts",
                "Report every material issue with severity and category",
                "Clear initial discovery still requires a separate fresh scope review",
                "Do not treat this pass as final approval",
                "Echo finding_set_id unchanged; service derives lifecycle outcomes",
                "Do not omit lower-severity issues because they may not force revision",
            ]
        else:
            raise ValueError(
                f"initial_review guidance is only defined for mandatory whole_* loops; "
                f"got {loop.type!r}"
            )
    return fields


def prepare_focused_verification_recheck(
    loop: ReviewLoop,
    *,
    target_revision: int,
) -> ReviewLoop:
    """Enter focused finding_verification without mandatory lifecycle transitions."""

    return replace(
        loop,
        target_revision=target_revision,
        status="pending",
        active_stage="finding_verification",
        approved_digests=None,
    )


def verification_recheck_request(
    *,
    phase: str,
    loop: ReviewLoop,
    target_revision: int,
) -> dict[str, Any]:
    from top_down_planning.orchestrator.reviewer_session import (
        build_reviewer_protocol_instructions,
    )

    staged = replace(loop, active_stage="finding_verification")
    package_fields = stage_package_fields(staged)
    active = build_active_findings_view(loop)
    return {
        "action": "finding_verification",
        "phase": phase,
        "loop_id": loop.id,
        "target_revision": target_revision,
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage="finding_verification"
        ),
        **active,
        **package_fields,
    }


def limit_message(
    limits: MandatoryReviewLimits,
    *,
    exhausted: Literal["verification_revision", "scope_review"],
    review_label: str,
) -> str:
    if exhausted == "verification_revision":
        return (
            f"{review_label} exceeded max_revision_cycles "
            f"({limits.max_revision_cycles})"
        )
    return (
        f"{review_label} exceeded max_scope_review_rounds "
        f"({limits.max_scope_review_rounds})"
    )
