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
    ready_for_mandatory_final_approval,
    reviewer_package_policy_guidance,
    needs_fresh_scope_review_clear,
    reset_gate_agent_turns,
)

ReviewArtifactKind = Literal["plan", "output"]

_FOLLOW_PROTOCOL_INITIAL_REVIEW = (
    "Follow protocol_instructions for mandatory whole_* initial_review behavior."
)
_FOLLOW_PROTOCOL_VERIFICATION = (
    "Follow protocol_instructions for finding_verification stage behavior."
)
_FRESH_SCOPE_REVIEW_PURPOSE = (
    "Fresh scope review per protocol_instructions; omit prior finding framing."
)

_INITIAL_STAGES = frozenset({None, "initial_review"})
_VERIFICATION_STAGES = frozenset({"finding_verification"})
_SCOPE_REVIEW_STAGES = frozenset({"scope_review"})

_MANDATORY_FAMILY_DISCOVERY_REQUIRED = (
    "target_revision",
    "finding_set_id",
    "target_digest",
    "reported_findings",
    "finding_families",
    "audit_attestation",
    "review_completed",
    "summary",
)

_MANDATORY_FAMILY_VERIFICATION_REQUIRED = (
    "target_revision",
    "finding_results",
    "family_results",
    "new_direct_side_effect_findings",
    "target_digest",
    "finding_set_id",
    "summary",
)


def _mandatory_family_discovery_contract(stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "required_fields": list(_MANDATORY_FAMILY_DISCOVERY_REQUIRED),
    }


def _mandatory_family_verification_contract() -> dict[str, Any]:
    return {
        "stage": "finding_verification",
        "decisions": ["verified", "needs_revision", "blocked"],
        "required_fields": list(_MANDATORY_FAMILY_VERIFICATION_REQUIRED),
    }


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

    updated = replace(
        loop,
        lifecycle_status=target,  # type: ignore[arg-type]
        active_stage="finding_verification",
        finding_set_id=finding_set_id,
        revision_cycles=revision_cycles,
        approved_digests=None,
        scope_review_result=None,
    )
    return reset_gate_agent_turns(updated)


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


def enter_owner_revision_cycle(loop: ReviewLoop) -> ReviewLoop:
    """Enter owner revision after needs_revision / changes_requested."""

    current = loop.lifecycle_status or "findings_open"
    if current == "revision_in_progress":
        return replace(
            loop,
            status="pending",
            active_stage="finding_verification",
            pending_revision_cycle_entry=False,
        )
    return replace(
        mark_revision_in_progress(loop),
        pending_revision_cycle_entry=False,
    )


def mandatory_orchestration_decision(loop: ReviewLoop) -> str:
    """Stage-native decision that drives mandatory review orchestration."""

    return mandatory_stage_respond_decision(loop)


def mark_verification_pending(loop: ReviewLoop, *, target_revision: int) -> ReviewLoop:
    current = loop.lifecycle_status or "revision_in_progress"
    pending = replace(
        loop,
        target_revision=target_revision,
        status="pending",
        active_stage="finding_verification",
        approved_digests=None,
        verification_result=None,
    )
    if current == "verification_pending":
        return reset_gate_agent_turns(
            replace(pending, lifecycle_status="verification_pending")
        )
    assert_mandatory_review_transition(current, "verification_pending")
    return reset_gate_agent_turns(
        replace(pending, lifecycle_status="verification_pending")
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
    if current != "scope_review_pending":
        assert_mandatory_review_transition(current, "scope_review_pending")

    prepared = replace(
        loop,
        status="pending",
        lifecycle_status="scope_review_pending",
        active_stage=SCOPE_REVIEW_STAGE,
        approved_digests=None,
        scope_review_result=None,
    )
    prepared, _finding_set_id = allocate_discovery_finding_set_id(
        prepared,
        fresh=True,
    )
    return reset_gate_agent_turns(prepared.with_reviewer_session_released())


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
        # verification_revision pauses before enter_revision_cycle increments;
        # preserve that fact so limit-extension resume can charge exactly once.
        pending_revision_cycle_entry=(exhausted == "verification_revision"),
    )


def approved_means_final_approval(loop: ReviewLoop) -> bool:
    """True when an approved orchestration decision applies at the scope-review stage."""

    return is_scope_review_stage(loop)


def approved_means_start_scope_review(loop: ReviewLoop) -> bool:
    """True when ``approved`` means findings closed / no findings → scope gate."""

    if is_scope_review_stage(loop):
        return False
    return not required_unresolved_finding_ids(
        loop.findings,
        revise_at=loop_revise_at(loop),
    )


def _focused_verification_package_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Verification-stage package fields for focused (non-mandatory) rechecks."""

    fields: dict[str, Any] = {
        "stage": "finding_verification",
        "lifecycle_status": loop.lifecycle_status or "review_pending",
        "review_policy": reviewer_package_policy_guidance(),
    }
    if loop.finding_set_id is not None:
        fields["finding_set_id"] = loop.finding_set_id
    fields["verification_guidance"] = [_FOLLOW_PROTOCOL_VERIFICATION]
    fields["respond_contract"] = {
        "stage": "finding_verification",
        "decisions": ["verified", "needs_revision", "blocked"],
        "required_fields": [
            "target_revision",
            "finding_results",
            "new_direct_side_effect_findings",
            "target_digest",
            "finding_set_id",
            "summary",
        ],
    }
    return fields


def stage_package_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Fields embedded in mandatory whole_* reviewer packages for stage awareness."""

    from top_down_planning.domain.reviews import (
        is_mandatory_whole_review,
        validate_review_stage,
    )

    if not is_mandatory_whole_review(loop):
        raise ValueError(
            "stage_package_fields applies only to mandatory whole_* reviews; "
            f"got {loop.type!r}"
        )

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
            "purpose": _FRESH_SCOPE_REVIEW_PURPOSE,
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
        fields["respond_contract"] = _mandatory_family_discovery_contract(
            SCOPE_REVIEW_STAGE
        )
    elif stage == "finding_verification":
        if loop.finding_set_id is not None:
            fields["finding_set_id"] = loop.finding_set_id
        fields["verification_guidance"] = [_FOLLOW_PROTOCOL_VERIFICATION]
        fields["respond_contract"] = _mandatory_family_verification_contract()
    else:
        if loop.finding_set_id is not None:
            fields["finding_set_id"] = loop.finding_set_id
        fields["respond_contract"] = _mandatory_family_discovery_contract(
            "initial_review"
        )
        if loop.type == "whole_plan":
            fields["initial_review_guidance"] = [_FOLLOW_PROTOCOL_INITIAL_REVIEW]
        elif loop.type == "whole_output":
            fields["initial_review_guidance"] = [_FOLLOW_PROTOCOL_INITIAL_REVIEW]
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

    return reset_gate_agent_turns(
        replace(
            loop,
            target_revision=target_revision,
            status="pending",
            active_stage="finding_verification",
            approved_digests=None,
            verification_result=None,
        )
    )


def verification_recheck_request(
    *,
    phase: str,
    loop: ReviewLoop,
    target_revision: int,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    from top_down_planning.orchestrator.reviewer_session import (
        build_reviewer_protocol_instructions,
    )

    from top_down_planning.domain.reviews import (
        is_mandatory_whole_review,
        loop_uses_finding_families,
    )

    staged = replace(loop, active_stage="finding_verification")
    package_fields = (
        stage_package_fields(staged)
        if is_mandatory_whole_review(loop)
        else _focused_verification_package_fields(staged)
    )
    active = build_active_findings_view(loop)
    request: dict[str, Any] = {
        "action": "finding_verification",
        "phase": phase,
        "loop_id": loop.id,
        "target_revision": target_revision,
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage="finding_verification",
            review_type=loop.type,
        ),
        **active,
        **package_fields,
    }
    if loop_uses_finding_families(loop) and not is_mandatory_whole_review(loop):
        from top_down_planning.domain.finding_families import build_active_family_view

        request["active_families"] = build_active_family_view(
            loop,
            artifact_revision=target_revision,
            artifact_digest=str(artifact_digest or "").strip() or None,
        )
    return request


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
