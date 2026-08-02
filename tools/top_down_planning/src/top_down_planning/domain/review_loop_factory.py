"""Factories for review loop creation."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.review_policy import resolved_revise_at
from top_down_planning.domain.reviews import (
    CURRENT_REVIEW_CONTRACT_VERSION,
    CURRENT_REVIEW_RECORD_SCHEMA_VERSION,
    ReviewLoop,
    ReviewLoopType,
)


def _version_fields(*, record: int, contract: int) -> dict[str, int]:
    return {
        "review_record_schema_version": record,
        "review_contract_version": contract,
    }


def new_whole_plan_review_loop(
    *,
    loop_id: str,
    target_revision: int,
    config: dict[str, Any],
) -> ReviewLoop:
    return ReviewLoop(
        id=loop_id,
        type="whole_plan",
        target_revision=target_revision,
        scope={"kind": "whole_plan"},
        status="pending",
        lifecycle_status="review_pending",
        active_stage=None,
        scope_review_rounds=0,
        revise_at=resolved_revise_at(config, "whole_plan"),
        **_version_fields(
            record=CURRENT_REVIEW_RECORD_SCHEMA_VERSION,
            contract=CURRENT_REVIEW_CONTRACT_VERSION,
        ),
    )


def new_whole_output_review_loop(
    *,
    loop_id: str,
    target_revision: int,
    config: dict[str, Any],
) -> ReviewLoop:
    return ReviewLoop(
        id=loop_id,
        type="whole_output",
        target_revision=target_revision,
        scope={"kind": "whole_output"},
        status="pending",
        lifecycle_status="review_pending",
        active_stage=None,
        scope_review_rounds=0,
        revise_at=resolved_revise_at(config, "whole_output"),
        **_version_fields(
            record=CURRENT_REVIEW_RECORD_SCHEMA_VERSION,
            contract=CURRENT_REVIEW_CONTRACT_VERSION,
        ),
    )


def new_focused_review_loop(
    *,
    loop_id: str,
    review_type: ReviewLoopType,
    target_revision: int,
    scope: dict[str, Any],
    config: dict[str, Any],
) -> ReviewLoop:
    if review_type not in {"focused_plan", "focused_output"}:
        raise ValueError("focused review factory requires focused_plan or focused_output")
    return ReviewLoop(
        id=loop_id,
        type=review_type,
        target_revision=target_revision,
        scope=scope,
        status="pending",
        revise_at=resolved_revise_at(config, review_type),
        **_version_fields(
            record=CURRENT_REVIEW_RECORD_SCHEMA_VERSION,
            contract=1,
        ),
    )
