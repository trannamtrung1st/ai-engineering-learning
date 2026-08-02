"""Shared mandatory whole-artifact review run loop (plan and output)."""

from __future__ import annotations

from typing import Any, Protocol

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.review_loop_driver import (
    ReviewLoopAdapter,
    ReviewLoopDriver,
)
from top_down_planning.orchestrator.review_loop_types import (
    MandatoryWholeReviewResult,
    MandatoryWholeReviewSpec,
    OwnerHandoff,
    reject_nonterminal_mandatory_contract_v1_loop,
)

__all__ = [
    "MandatoryWholeReviewAdapter",
    "MandatoryWholeReviewResult",
    "MandatoryWholeReviewSpec",
    "OwnerHandoff",
    "ReviewLoopAdapter",
    "ReviewLoopDriver",
    "reject_nonterminal_mandatory_contract_v1_loop",
]


class MandatoryWholeReviewAdapter(ReviewLoopAdapter, Protocol):
    @property
    def spec(self) -> MandatoryWholeReviewSpec: ...

    def preflight(self, loop: ReviewLoop | None) -> None: ...

    def current_artifact_binding(self) -> tuple[int, str]: ...

    def new_loop(self, loop_id: str) -> ReviewLoop: ...

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]: ...

    def primary_owner_session_id(self, run: dict[str, Any]) -> str | None: ...

    def build_owner_request(
        self,
        loop: ReviewLoop,
        config: dict[str, Any],
        handoff: OwnerHandoff,
    ) -> dict[str, Any]: ...

    def build_owner_turn_recovery(
        self,
        phase: str,
        append_event: Any,
        model: str | None,
    ) -> Any: ...

    def build_reviewer_turn_recovery(
        self,
        loop_id: str,
        phase: str,
        append_event: Any,
        model: str | None,
        review_package: dict[str, Any],
    ) -> Any: ...

    def after_owner_turn(self, session_id: str) -> None: ...

    def complete_approval(self, loop: ReviewLoop) -> MandatoryWholeReviewResult: ...
