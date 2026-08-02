"""Resolved mandatory-review targets for artifact-neutral protocol routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.artifact_refs import ArtifactRefKind
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.review_analysis_context import (
    required_audit_passes,
    rubric_items_with_ids,
)
from top_down_planning.persistence.interface import RunStore


MandatoryArtifactKind = Literal["plan", "output"]
MandatoryFamilyScopeKind = Literal["active-plan", "whole-output"]
FocusedFamilyScopeKind = Literal["focused-plan", "focused-output"]
FamilyScopeKind = MandatoryFamilyScopeKind | FocusedFamilyScopeKind


@dataclass(frozen=True)
class MandatoryReviewTarget:
    review_type: str
    artifact_kind: MandatoryArtifactKind
    artifact_revision: int
    artifact_digest: str
    rubric_items: tuple[dict[str, str], ...]
    required_audit_passes: tuple[str, ...]
    family_scope_kind: FamilyScopeKind
    allowed_artifact_ref_kinds: frozenset[str]


_PLAN_REF_KINDS = frozenset({"plan_item_field", "plan_dependency"})
_OUTPUT_REF_KINDS = frozenset({"output_path", "output_record"})


def resolve_focused_review_target(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    artifact_revision: int,
    artifact_digest: str,
) -> MandatoryReviewTarget:
    review_type = str(loop.type)
    if review_type == "focused_plan":
        family_scope_kind: FamilyScopeKind = "focused-plan"
        allowed = _PLAN_REF_KINDS
        artifact_kind: MandatoryArtifactKind = "plan"
    elif review_type == "focused_output":
        family_scope_kind = "focused-output"
        allowed = _OUTPUT_REF_KINDS
        artifact_kind = "output"
    else:
        raise ValueError(
            f"focused review target resolution requires focused_plan or focused_output; "
            f"got {review_type!r}"
        )

    return MandatoryReviewTarget(
        review_type=review_type,
        artifact_kind=artifact_kind,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
        rubric_items=(),
        required_audit_passes=(),
        family_scope_kind=family_scope_kind,
        allowed_artifact_ref_kinds=allowed,
    )


def resolve_mandatory_review_target(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    artifact_revision: int,
    artifact_digest: str,
) -> MandatoryReviewTarget:
    config = store.load_resolved_config(run_id)
    review_type = str(loop.type)
    if review_type == "whole_plan":
        artifact_kind: MandatoryArtifactKind = "plan"
        family_scope_kind: MandatoryFamilyScopeKind = "active-plan"
        allowed = _PLAN_REF_KINDS
    elif review_type == "whole_output":
        artifact_kind = "output"
        family_scope_kind = "whole-output"
        allowed = _OUTPUT_REF_KINDS
    else:
        raise ValueError(
            f"mandatory review target resolution requires whole_plan or whole_output; "
            f"got {review_type!r}"
        )

    review_cfg = (config.get("review") or {}).get(review_type) or {}
    rubric = list(
        review_cfg.get("rubric")
        or DEFAULT_CONFIG["review"].get(review_type, {}).get("rubric", [])
    )
    rubric_items = tuple(
        rubric_items_with_ids([str(item) for item in rubric])
    )
    return MandatoryReviewTarget(
        review_type=review_type,
        artifact_kind=artifact_kind,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
        rubric_items=rubric_items,
        required_audit_passes=required_audit_passes(review_type),
        family_scope_kind=family_scope_kind,
        allowed_artifact_ref_kinds=allowed,
    )


def validate_instance_ref_kind(
    ref_kind: str,
    *,
    allowed_kinds: frozenset[str],
) -> None:
    if ref_kind not in allowed_kinds:
        raise ValueError(
            f"artifact ref kind {ref_kind!r} is not allowed for this mandatory review target"
        )


__all__ = [
    "MandatoryReviewTarget",
    "resolve_focused_review_target",
    "resolve_mandatory_review_target",
    "validate_instance_ref_kind",
]
