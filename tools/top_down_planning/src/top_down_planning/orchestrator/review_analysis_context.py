"""Review package analysis context and family views."""

from __future__ import annotations

from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.digest import digest_canonical_payload
from top_down_planning.domain.mandatory_audit_passes import (
    WHOLE_OUTPUT_AUDIT_PASS_IDS,
    WHOLE_PLAN_AUDIT_PASS_IDS,
    mandatory_audit_pass_ids_for_loop,
)
from top_down_planning.domain.models import Plan
from top_down_planning.domain.output_validators import validate_production_checks
from top_down_planning.domain.production import build_output_traceability
from top_down_planning.domain.reviews import (
    ReviewLoop,
    is_mandatory_whole_review,
)
from top_down_planning.domain.validators import collect_plan_analysis_validation_issues


def required_audit_passes(review_type: str) -> tuple[str, ...]:
    if review_type == "whole_plan":
        return WHOLE_PLAN_AUDIT_PASS_IDS
    if review_type == "whole_output":
        return WHOLE_OUTPUT_AUDIT_PASS_IDS
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


def build_output_analysis_context(
    plan: Plan,
    production: dict[str, Any],
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
    traceability = build_output_traceability(plan, production)
    validation_issues = [
        {
            "code": "output_check_failed",
            "severity": "warning",
            "message": message,
        }
        for message in validate_production_checks(plan, production)
    ]
    return {
        "audit_passes": list(required_audit_passes(review_type)),
        "rubric_items": rubric_items,
        "validation_issues": validation_issues,
        "traceability_summary": {
            "plan_contract_item_count": len(traceability.get("plan_contracts") or []),
            "evidence_item_count": len(traceability.get("evidence_by_item") or {}),
            "output_revision": int(production.get("output_revision") or 0),
        },
        "preflight_is_advisory": True,
        "stage": stage,
    }


def contract_fields(loop: ReviewLoop) -> dict[str, Any]:
    return {
        "review_record_schema_version": loop.review_record_schema_version,
        "review_contract_version": loop.review_contract_version,
        "family_protocol_enabled": is_mandatory_whole_review(loop),
    }


__all__ = [
    "build_active_family_view",
    "build_family_verification_view",
    "build_output_analysis_context",
    "build_plan_analysis_context",
    "contract_fields",
    "required_audit_passes",
    "rubric_items_with_ids",
    "WHOLE_OUTPUT_AUDIT_PASS_IDS",
    "WHOLE_PLAN_AUDIT_PASS_IDS",
]
