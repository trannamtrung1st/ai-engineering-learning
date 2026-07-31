"""Shared mandatory review stage transitions (proposal lifecycle)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from top_down_planning.domain.reviews import (
    ExhaustedReviewBudget,
    MandatoryReviewLimits,
    ReviewLoop,
    blocking_unresolved_finding_ids,
    build_limit_reached_terminal,
    assert_mandatory_review_transition,
    loop_revise_at,
    mandatory_stage_respond_decision,
)

ReviewArtifactKind = Literal["plan", "output"]

_INITIAL_STAGES = frozenset({None, "initial_review"})
_VERIFICATION_STAGES = frozenset({"finding_verification"})
_BLOCKER_STAGES = frozenset({"scope_blocker_review"})


def is_blocker_stage(loop: ReviewLoop) -> bool:
    return loop.active_stage in _BLOCKER_STAGES


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
        blocker_review_rounds=loop.blocker_review_rounds,
    )


def next_finding_set_id(loop: ReviewLoop) -> str:
    base = loop.id
    existing = loop.finding_set_id or ""
    suffix = 1
    if existing.startswith(f"{base}-fs-"):
        try:
            suffix = int(existing.rsplit("-", 1)[-1]) + 1
        except ValueError:
            suffix = 1
    return f"{base}-fs-{suffix:02d}"


def mark_findings_open(loop: ReviewLoop) -> ReviewLoop:
    """Enter Stage-1 after findings (or blockers) are raised."""

    current = loop.lifecycle_status or "review_pending"
    from_blocker = loop.active_stage == "scope_blocker_review"

    if from_blocker:
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
        blocker_review_result=None,
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
    """Enter planner revision after needs_revision / blockers_found / changes_requested."""

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


def prepare_blocker_review_loop(loop: ReviewLoop) -> ReviewLoop:
    """Reset for a fresh scope-complete blocker review (approval gate).

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
    assert_mandatory_review_transition(current, "blocker_review_pending")

    return replace(
        loop,
        status="pending",
        reviewer_session_id=None,
        lifecycle_status="blocker_review_pending",
        active_stage="scope_blocker_review",
        blocker_review_rounds=loop.blocker_review_rounds + 1,
        approved_digests=None,
        blocker_review_result=None,
    )


def mark_mandatory_approved(loop: ReviewLoop) -> ReviewLoop:
    if loop.lifecycle_status == "approved":
        return replace(
            loop,
            lifecycle_status="approved",
            status="approve",
            active_stage="scope_blocker_review",
        )
    current = loop.lifecycle_status or "blocker_review_pending"
    assert_mandatory_review_transition(current, "approved")
    return replace(
        loop,
        lifecycle_status="approved",
        status="approve",
        active_stage="scope_blocker_review",
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
        exhausted_budget=exhausted,
    )


def approved_means_final_approval(loop: ReviewLoop) -> bool:
    """True when ``approved`` may complete the mandatory gate (blocker clear)."""

    return is_blocker_stage(loop)


def approved_means_start_blocker_review(loop: ReviewLoop) -> bool:
    """True when ``approved`` means findings closed / no findings → blocker gate."""

    if is_blocker_stage(loop):
        return False
    return not blocking_unresolved_finding_ids(
        loop.findings,
        revise_at=loop_revise_at(loop),
    )


def stage_package_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Fields embedded in reviewer packages for stage awareness."""

    stage = loop.active_stage or "initial_review"
    fields: dict[str, Any] = {
        "stage": stage,
        "lifecycle_status": loop.lifecycle_status or "review_pending",
    }
    if stage == "scope_blocker_review":
        # Freshness: omit finding_set_id and prior finding lists from framing.
        fields["freshness"] = {
            "omit_prior_finding_framing": True,
            "include_prior_findings": False,
            "purpose": (
                "Scope-complete blocker review: search for remaining approval "
                "blockers within the current scope without anchoring on prior "
                "finding discussion."
            ),
        }
        if loop.type == "whole_plan":
            fields["blocker_scope_guidance"] = [
                "coverage of the original request",
                "required deliverables",
                "actionable completeness",
                "dependency and sequencing validity",
                "feasibility",
                "contradictions",
                "unresolved assumptions that prevent execution",
                "applicable planning acceptance criteria",
            ]
        else:
            fields["blocker_scope_guidance"] = [
                "conformance to the approved plan",
                "required deliverables",
                "correctness",
                "missing required content",
                "material cross-output inconsistency",
                "broken references or dependencies",
                "applicable output acceptance criteria",
                "regressions that prevent use or acceptance",
            ]
        fields["respond_contract"] = {
            "stage": "scope_blocker_review",
            "decisions": ["approve", "blockers_found", "blocked"],
            "required_fields": [
                "blocking_findings",
                "acceptance_criteria_checked",
                "target_digest",
                "scope_id",
                "summary",
            ],
        }
    elif stage == "finding_verification":
        if loop.finding_set_id is not None:
            fields["finding_set_id"] = loop.finding_set_id
        fields["verification_guidance"] = [
            "Verify each finding was addressed",
            "Confirm required outcomes and evidence",
            "Check direct revision side effects only",
            "Do not search broadly for unrelated issues",
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
        fields["respond_contract"] = {
            "stage": "initial_review",
            "decisions": ["approved", "changes_requested", "blocked"],
            "required_fields": ["findings", "target_digest"],
        }
        fields["initial_review_guidance"] = [
            "Mandatory review gate: initial discovery may raise findings",
            "Clear initial approval still requires a separate scope_blocker_review",
            "Do not treat this pass as final approval",
        ]
    return fields


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
    return {
        "action": "finding_verification",
        "phase": phase,
        "loop_id": loop.id,
        "target_revision": target_revision,
        "findings": [finding.to_dict() for finding in loop.findings],
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage="finding_verification"
        ),
        **package_fields,
    }


def limit_message(
    limits: MandatoryReviewLimits,
    *,
    exhausted: Literal["verification_revision", "blocker_review"],
    review_label: str,
) -> str:
    if exhausted == "verification_revision":
        return (
            f"{review_label} exceeded max_revision_cycles "
            f"({limits.max_revision_cycles})"
        )
    return (
        f"{review_label} exceeded max_blocker_review_rounds "
        f"({limits.max_blocker_review_rounds})"
    )
