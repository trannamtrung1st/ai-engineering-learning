"""Default review-loop adapter hooks for mandatory whole-artifact reviews."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.mandatory_review_stages import (
    enter_owner_revision_cycle,
    mark_verification_pending,
)
from top_down_planning.orchestrator.review_loop_profile import (
    MANDATORY_WHOLE_PROFILE,
    ReviewLoopProfile,
)


class MandatoryReviewLoopAdapterMixin:
    """Shared adapter hooks for whole_plan / whole_output mandatory gates."""

    @property
    def profile(self) -> ReviewLoopProfile:
        return MANDATORY_WHOLE_PROFILE

    def phase_for_session(self, loop: ReviewLoop, run: dict[str, Any]) -> str:
        return str(run.get("phase") or self.spec.phase)

    def prepare_recheck_transition(
        self, loop: ReviewLoop, target_revision: int
    ) -> ReviewLoop:
        return mark_verification_pending(loop, target_revision=target_revision)

    def enter_revision_cycle(
        self, loop: ReviewLoop, revision_cycles: int
    ) -> ReviewLoop:
        return enter_owner_revision_cycle(
            replace(loop, revision_cycles=revision_cycles)
        )

    def complete_success(self, loop: ReviewLoop) -> Any:
        return self.complete_approval(loop)

    def reviewer_session_started_scope(
        self, loop: ReviewLoop
    ) -> dict[str, Any] | None:
        return None
