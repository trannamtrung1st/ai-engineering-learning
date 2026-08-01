"""Plan document schema version gate (v2-only, no migrator)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.errors import UnsupportedPlanSchemaVersionError

PLAN_SCHEMA_VERSION = 2

UNSUPPORTED_PLAN_SCHEMA_MESSAGE = (
    "Unsupported plan schema version. Recreate the run using the current TDP version."
)


def validate_plan_schema_version(payload: dict[str, Any]) -> int:
    """Validate top-level plan ``schema_version`` before nested field use.

    Missing or unsupported values fail at this boundary with the recreate
    message so callers do not surface incidental nested-field errors first.
    """

    if "schema_version" not in payload:
        raise UnsupportedPlanSchemaVersionError(UNSUPPORTED_PLAN_SCHEMA_MESSAGE)

    raw = payload["schema_version"]
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise UnsupportedPlanSchemaVersionError(UNSUPPORTED_PLAN_SCHEMA_MESSAGE)
    if raw != PLAN_SCHEMA_VERSION:
        raise UnsupportedPlanSchemaVersionError(UNSUPPORTED_PLAN_SCHEMA_MESSAGE)
    return raw


def _coerce_string_list(value: Any, *, field_label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_label} must be a list")
    return list(value)


def normalize_plan_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Validate schema v2 and coerce optional list fields to lists."""

    if "revision" not in data:
        raise ValueError("plan revision is required")

    validate_plan_schema_version(data)

    normalized = dict(data)
    normalized["schema_version"] = PLAN_SCHEMA_VERSION
    normalized["risks"] = _coerce_string_list(
        normalized.get("risks"),
        field_label="plan risks",
    )

    items: list[dict[str, Any]] = []
    for raw_item in normalized.get("items") or []:
        if not isinstance(raw_item, dict):
            raise ValueError("each plan item must be an object")
        item = dict(raw_item)
        item["risks"] = _coerce_string_list(
            item.get("risks"),
            field_label="plan item risks",
        )
        item["source_refs"] = _coerce_string_list(
            item.get("source_refs"),
            field_label="plan item source_refs",
        )
        items.append(item)
    normalized["items"] = items
    return normalized


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "UNSUPPORTED_PLAN_SCHEMA_MESSAGE",
    "UnsupportedPlanSchemaVersionError",
    "normalize_plan_payload",
    "validate_plan_schema_version",
]
