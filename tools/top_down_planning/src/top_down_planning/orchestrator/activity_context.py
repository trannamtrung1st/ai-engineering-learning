"""Activity-aware session continuation decisions."""

from __future__ import annotations

from typing import Literal

from top_down_planning.config import EffectiveActivityContext
from top_down_planning.config.activities import ACTIVITY_ROLE_MAP
from top_down_planning.domain.session_bindings import SessionBinding

SessionContinuationDecision = Literal["resume", "fresh"]

_REVIEWER_STAGE_ACTIVITIES: dict[str, str] = {
    "initial_review": "initial_review",
    "finding_verification": "finding_verification",
    "scope_review": "scope_review",
}


def resolve_activity_for_reviewer_stage(active_stage: str | None) -> str:
    """Map a reviewer loop stage name to its agent activity."""

    stage = str(active_stage or "initial_review").strip() or "initial_review"
    activity = _REVIEWER_STAGE_ACTIVITIES.get(stage)
    if activity is None:
        raise ValueError(f"unsupported reviewer stage for activity mapping: {stage!r}")
    if activity not in ACTIVITY_ROLE_MAP:
        raise ValueError(f"reviewer activity not registered: {activity!r}")
    return activity


def session_continuation_decision(
    binding: SessionBinding,
    requested: EffectiveActivityContext,
) -> SessionContinuationDecision:
    """Return whether the bound primary session can resume for the requested context."""

    if binding.state != "bound":
        return "fresh"
    if binding.role != requested.role:
        return "fresh"
    if binding.activity != requested.activity:
        return "fresh"
    if binding.context_digest != requested.context_digest:
        return "fresh"
    return "resume"


def owner_revision_activity(owner_role: str) -> str:
    """Return the revision activity for a primary owner role."""

    role = str(owner_role).strip()
    if role == "planner":
        return "plan_revision"
    if role == "producer":
        return "output_revision"
    raise ValueError(f"unsupported owner role for revision activity: {owner_role!r}")


__all__ = [
    "ACTIVITY_ROLE_MAP",
    "SessionContinuationDecision",
    "owner_revision_activity",
    "resolve_activity_for_reviewer_stage",
    "session_continuation_decision",
]
