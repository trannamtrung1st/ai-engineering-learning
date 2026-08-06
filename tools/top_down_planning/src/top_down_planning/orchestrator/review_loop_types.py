"""Shared types for mandatory and focused review-loop drivers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from top_down_planning.domain.reviews import (
    ReviewLoop,
    uses_finding_family_protocol,
)
from top_down_planning.orchestrator.errors import ProviderRunError

OwnerHandoff = Literal["revision", "advisory"]


@dataclass(frozen=True)
class MandatoryWholeReviewSpec:
    review_type: str
    phase: str
    approved_phase: str
    owner_role: str
    limits_key: str
    event_prefix: str
    loop_id_prefix: str
    review_label: str


@dataclass(frozen=True)
class MandatoryWholeReviewResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    loop_id: str | None
    reviewer_session_id: str | None
    revision_cycles: int
    reason: str | None = None


def reject_mandatory_contract_v1_loop(loop: ReviewLoop) -> None:
    """Reject mandatory whole-artifact loops that predate contract v2."""

    if loop.type not in {"whole_plan", "whole_output"}:
        return
    if uses_finding_family_protocol(loop):
        return
    label = loop.type.replace("_", "-")
    raise ProviderRunError(
        f"This run predates mandatory {label} contract v2 and must be recreated. "
        f"Contract-v1 review records are not supported."
    )
