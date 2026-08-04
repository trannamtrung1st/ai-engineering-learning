"""Build narrow prompt contexts for role protocol templates."""

from __future__ import annotations

from top_down_planning.domain.plan_tree import DEFAULT_PLAN_ROOT_TITLE, PLAN_ROOT_ITEM_ID
from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR

_VALID_REVIEW_TYPES = frozenset(
    {"whole_plan", "whole_output", "focused_plan", "focused_output"}
)
_VALID_REVIEWER_STAGES = frozenset(
    {"initial_review", "finding_verification", "scope_review"}
)


def planner_protocol_context() -> dict[str, str]:
    return {
        "plan_root_item_id": PLAN_ROOT_ITEM_ID,
        "plan_root_default_title": DEFAULT_PLAN_ROOT_TITLE,
    }


def producer_protocol_context() -> dict[str, str]:
    return {
        "capability_token_env_var": CAPABILITY_TOKEN_FILE_ENV_VAR,
    }


def _normalize_review_type(review_type: str | None) -> str | None:
    normalized = str(review_type or "").strip() or None
    if normalized is not None and normalized not in _VALID_REVIEW_TYPES:
        raise ValueError(f"unsupported review_type: {review_type!r}")
    return normalized


def _normalize_reviewer_stage(stage: str | None) -> str | None:
    normalized = str(stage or "").strip() or None
    if normalized is not None and normalized not in _VALID_REVIEWER_STAGES:
        raise ValueError(f"unsupported reviewer stage: {stage!r}")
    return normalized


def reviewer_protocol_context(
    *,
    stage: str | None = None,
    review_type: str | None = None,
) -> dict[str, object]:
    normalized_type = _normalize_review_type(review_type)
    normalized_stage = _normalize_reviewer_stage(stage)
    is_finding_verification = normalized_stage == "finding_verification"
    is_scope_review = normalized_stage == "scope_review"
    is_mandatory_family_review = normalized_type in {"whole_plan", "whole_output"}

    gate_label: str | None
    if normalized_type == "whole_plan":
        gate_label = "Whole-plan"
    elif normalized_type == "whole_output":
        gate_label = "Whole-output"
    else:
        gate_label = None

    return {
        "review_type": normalized_type or "",
        "plan_root_item_id": PLAN_ROOT_ITEM_ID,
        "plan_root_default_title": DEFAULT_PLAN_ROOT_TITLE,
        "gate_label": gate_label or "",
        "include_whole_plan_gate_focus": (
            normalized_type == "whole_plan" and not is_finding_verification
        ),
        "include_whole_output_gate_focus": (
            normalized_type == "whole_output" and not is_finding_verification
        ),
        "include_focused_plan_guidance": (
            normalized_type == "focused_plan" and not is_finding_verification
        ),
        "include_root_contract": (
            normalized_type in {"whole_plan", "focused_plan"}
            and not is_finding_verification
        ),
        "include_focused_rule_id_guidance": (
            normalized_type in {"focused_plan", "focused_output"}
            and not is_finding_verification
        ),
        "is_finding_verification": is_finding_verification,
        "is_scope_review": is_scope_review,
        "is_mandatory_family_review": is_mandatory_family_review,
        "requires_audit_attestation": (
            is_mandatory_family_review and not is_finding_verification
        ),
        "include_mandatory_discovery_blocks": (
            is_mandatory_family_review
            and normalized_stage in {None, "initial_review", "scope_review"}
        ),
        "include_mandatory_verification_sweep": (
            is_mandatory_family_review and is_finding_verification
        ),
    }


__all__ = [
    "planner_protocol_context",
    "producer_protocol_context",
    "reviewer_protocol_context",
]
