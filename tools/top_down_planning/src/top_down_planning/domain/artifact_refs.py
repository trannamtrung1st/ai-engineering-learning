"""Structured artifact references for review finding families."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Union

from top_down_planning.domain.digest import digest_canonical_payload
from top_down_planning.domain.review_schema import (
    require_non_empty_string,
    require_non_negative_int,
    require_optional_exact_string,
    require_optional_non_negative_int,
    require_output_record_kind,
)

ArtifactRefKind = Literal["plan_item_field", "plan_dependency", "output_path", "output_record"]

_PLAN_ITEM_FIELD_KIND = "plan_item_field"
_PLAN_DEPENDENCY_KIND = "plan_dependency"
_OUTPUT_PATH_KIND = "output_path"
_OUTPUT_RECORD_KIND = "output_record"


@dataclass(frozen=True)
class PlanItemFieldRef:
    kind: Literal["plan_item_field"]
    item_id: str
    field: str
    value_digest: str
    duplicate_ordinal: int | None = None
    position_hint: int | None = None


@dataclass(frozen=True)
class PlanDependencyRef:
    kind: Literal["plan_dependency"]
    item_id: str
    dependency_id: str


@dataclass(frozen=True)
class OutputPathRef:
    kind: Literal["output_path"]
    path: str
    content_digest: str | None = None


@dataclass(frozen=True)
class OutputRecordRef:
    kind: Literal["output_record"]
    record_kind: Literal[
        "batch",
        "output",
        "contribution",
        "evidence",
        "disposition",
        "completion_claim",
        "traceability",
    ]
    record_key: str
    field: str | None = None
    value_digest: str | None = None


ArtifactRef = Union[PlanItemFieldRef, PlanDependencyRef, OutputPathRef, OutputRecordRef]


def normalize_field_value(value: Any) -> Any:
    """Normalize a field value for digest computation."""

    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value.casefold().strip())
        return normalized
    if isinstance(value, list):
        return [normalize_field_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_field_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    return value


def digest_field_value(value: Any) -> str:
    return digest_canonical_payload({"value": normalize_field_value(value)})


def artifact_ref_canonical_key(ref: ArtifactRef) -> tuple[Any, ...]:
    if isinstance(ref, PlanItemFieldRef):
        return (
            ref.kind,
            ref.item_id,
            ref.field,
            ref.value_digest,
            ref.duplicate_ordinal,
        )
    if isinstance(ref, PlanDependencyRef):
        return (ref.kind, ref.item_id, ref.dependency_id)
    if isinstance(ref, OutputRecordRef):
        return (ref.kind, ref.record_kind, ref.record_key, ref.field, ref.value_digest)
    return (ref.kind, ref.path, ref.content_digest)


def artifact_refs_equal(left: ArtifactRef, right: ArtifactRef) -> bool:
    return artifact_ref_canonical_key(left) == artifact_ref_canonical_key(right)


def parse_artifact_ref(payload: Mapping[str, Any]) -> ArtifactRef:
    kind = require_non_empty_string(payload.get("kind"), "artifact ref kind")
    if kind == _PLAN_ITEM_FIELD_KIND:
        item_id = require_non_empty_string(payload.get("item_id"), "item_id")
        field = require_non_empty_string(payload.get("field"), "field")
        value_digest = require_non_empty_string(
            payload.get("value_digest"),
            "value_digest",
        )
        duplicate_ordinal = require_optional_non_negative_int(
            payload.get("duplicate_ordinal"),
            "duplicate_ordinal",
        )
        position_hint = require_optional_non_negative_int(
            payload.get("position_hint"),
            "position_hint",
        )
        return PlanItemFieldRef(
            kind="plan_item_field",
            item_id=item_id,
            field=field,
            value_digest=value_digest,
            duplicate_ordinal=duplicate_ordinal,
            position_hint=position_hint,
        )
    if kind == _PLAN_DEPENDENCY_KIND:
        item_id = require_non_empty_string(payload.get("item_id"), "item_id")
        dependency_id = require_non_empty_string(
            payload.get("dependency_id"),
            "dependency_id",
        )
        return PlanDependencyRef(
            kind="plan_dependency",
            item_id=item_id,
            dependency_id=dependency_id,
        )
    if kind == _OUTPUT_PATH_KIND:
        path = require_non_empty_string(payload.get("path"), "path")
        content_digest = require_optional_exact_string(
            payload.get("content_digest"),
            "content_digest",
        )
        return OutputPathRef(
            kind="output_path",
            path=path,
            content_digest=content_digest,
        )
    if kind == _OUTPUT_RECORD_KIND:
        record_kind = require_output_record_kind(
            payload.get("record_kind"),
            "record_kind",
        )
        record_key = require_non_empty_string(payload.get("record_key"), "record_key")
        field = require_optional_exact_string(payload.get("field"), "field")
        value_digest = require_optional_exact_string(
            payload.get("value_digest"),
            "value_digest",
        )
        return OutputRecordRef(
            kind="output_record",
            record_kind=record_kind,  # type: ignore[arg-type]
            record_key=record_key,
            field=field,
            value_digest=value_digest,
        )
    raise ValueError(f"unsupported artifact ref kind: {kind!r}")


def artifact_ref_to_dict(ref: ArtifactRef) -> dict[str, Any]:
    if isinstance(ref, PlanItemFieldRef):
        payload: dict[str, Any] = {
            "kind": ref.kind,
            "item_id": ref.item_id,
            "field": ref.field,
            "value_digest": ref.value_digest,
        }
        if ref.duplicate_ordinal is not None:
            payload["duplicate_ordinal"] = ref.duplicate_ordinal
        if ref.position_hint is not None:
            payload["position_hint"] = ref.position_hint
        return payload
    if isinstance(ref, PlanDependencyRef):
        return {
            "kind": ref.kind,
            "item_id": ref.item_id,
            "dependency_id": ref.dependency_id,
        }
    if isinstance(ref, OutputRecordRef):
        payload: dict[str, Any] = {
            "kind": ref.kind,
            "record_kind": ref.record_kind,
            "record_key": ref.record_key,
        }
        if ref.field is not None:
            payload["field"] = ref.field
        if ref.value_digest is not None:
            payload["value_digest"] = ref.value_digest
        return payload
    payload = {"kind": ref.kind, "path": ref.path}
    if ref.content_digest is not None:
        payload["content_digest"] = ref.content_digest
    return payload


def parse_artifact_ref_list(raw: Any) -> list[ArtifactRef]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("artifact refs must be a list")
    refs: list[ArtifactRef] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"artifact refs[{index}] must be an object")
        refs.append(parse_artifact_ref(item))
    return refs


def validate_artifact_ref_kinds(
    refs: list[ArtifactRef],
    allowed_kinds: frozenset[str],
    *,
    context: str,
) -> None:
    """Reject artifact refs whose kinds are not allowed for the mandatory review target."""

    if not allowed_kinds:
        return
    for ref in refs:
        if ref.kind not in allowed_kinds:
            raise ValueError(
                f"{context}: artifact ref kind {ref.kind!r} is not allowed for this "
                f"mandatory review (allowed: {sorted(allowed_kinds)})"
            )


FOCUSED_PLAN_REF_KINDS = frozenset({"plan_item_field", "plan_dependency"})
FOCUSED_OUTPUT_REF_KINDS = frozenset({"output_path", "output_record"})


def focused_allowed_ref_kinds(review_type: str) -> frozenset[str]:
    if review_type == "focused_plan":
        return FOCUSED_PLAN_REF_KINDS
    if review_type == "focused_output":
        return FOCUSED_OUTPUT_REF_KINDS
    raise ValueError(f"unsupported focused review type: {review_type!r}")


def artifact_ref_scope_item_ids(ref: ArtifactRef) -> set[str]:
    """Return plan item ids referenced by an artifact ref when scope-bound."""

    if isinstance(ref, (PlanItemFieldRef, PlanDependencyRef)):
        return {ref.item_id}
    if isinstance(ref, OutputRecordRef):
        return {ref.record_key}
    return set()


def validate_artifact_ref_within_scope(
    ref: ArtifactRef,
    *,
    allowed_item_ids: set[str],
    allowed_kinds: frozenset[str],
    context: str,
) -> None:
    validate_artifact_ref_kinds([ref], allowed_kinds, context=context)
    bound_items = artifact_ref_scope_item_ids(ref)
    if not bound_items:
        return
    if not bound_items.issubset(allowed_item_ids):
        outside = sorted(bound_items - allowed_item_ids)
        raise ValueError(
            f"{context}: instance_ref references item ids outside declared scope: "
            f"{outside}"
        )
