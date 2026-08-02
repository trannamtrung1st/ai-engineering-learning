"""Review package analysis context and family views."""

from __future__ import annotations

from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.digest import digest_canonical_payload
from top_down_planning.domain.finding_families import (
    WHOLE_PLAN_AUDIT_PASS_IDS,
    build_active_family_view,
    build_family_verification_view,
)
from top_down_planning.domain.models import Plan
from top_down_planning.domain.reviews import ReviewLoop, uses_finding_family_protocol
from top_down_planning.domain.validators import collect_plan_analysis_validation_issues


def required_audit_passes(review_type: str) -> tuple[str, ...]:
    if review_type == "whole_plan":
        return WHOLE_PLAN_AUDIT_PASS_IDS
    return ()


def rubric_items_with_ids(rubric: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for index, text in enumerate(rubric, start=1):
        digest_suffix = digest_canonical_payload({"text": text})[:8]
        items.append(
            {
                "id": f"rubric-{index:02d}-{digest_suffix}",
                "text": text,
            }
        )
    return items


def build_plan_analysis_context(
    plan: Plan,
    config: dict[str, Any],
    *,
    stage: str | None,
    review_type: str,
) -> dict[str, Any]:
    review_cfg = (config.get("review") or {}).get(review_type) or {}
    rubric = list(
        review_cfg.get("rubric")
        or DEFAULT_CONFIG["review"].get(review_type, {}).get("rubric", [])
    )
    rubric_items = rubric_items_with_ids([str(item) for item in rubric])
    issues = collect_plan_analysis_validation_issues(plan)
    return {
        "audit_passes": list(required_audit_passes(review_type)),
        "rubric_items": rubric_items,
        "validation_issues": [issue.to_dict() for issue in issues],
        "preflight_is_advisory": True,
        "stage": stage,
    }


def contract_fields(loop: ReviewLoop) -> dict[str, Any]:
    return {
        "review_record_schema_version": loop.review_record_schema_version,
        "review_contract_version": loop.review_contract_version,
        "family_protocol_enabled": uses_finding_family_protocol(loop),
    }


__all__ = [
    "build_active_family_view",
    "build_family_verification_view",
    "build_plan_analysis_context",
    "contract_fields",
    "required_audit_passes",
    "rubric_items_with_ids",
]
