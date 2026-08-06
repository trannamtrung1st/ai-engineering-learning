"""Plan document schema version gate (v2-only, no migrator)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.errors import UnsupportedPlanSchemaVersionError

PLAN_SCHEMA_VERSION = 2

PLANNING_STATUSES = frozenset({"open", "superseded", "removed"})
ITEM_KINDS = frozenset({"aggregate", "work"})

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
    normalized: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str):
            raise ValueError(f"{field_label}[{index}] must be a string")
        normalized.append(entry)
    return normalized


def require_int_not_bool(value: Any, field_label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_label} must be an integer")
    return value


def require_non_negative_int(value: Any, field_label: str) -> int:
    result = require_int_not_bool(value, field_label)
    if result < 0:
        raise ValueError(f"{field_label} must be non-negative")
    return result


def require_string(value: Any, field_label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_label} must be a string")
    return value


def require_optional_string(value: Any, field_label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_label} must be a string or null")
    return value


def require_planning_status(value: Any) -> str:
    if value is None:
        raise ValueError("planning_status is required")
    status = require_string(value, "planning_status")
    if status not in PLANNING_STATUSES:
        raise ValueError(
            "planning_status must be one of: "
            + ", ".join(sorted(PLANNING_STATUSES))
        )
    return status


def require_scope_dict(value: Any, *, field_label: str) -> dict[str, list[str]]:
    if value is None:
        return {"includes": [], "excludes": []}
    if not isinstance(value, dict):
        raise ValueError(f"{field_label} must be an object")
    return {
        "includes": _coerce_string_list(
            value.get("includes"),
            field_label=f"{field_label}.includes",
        ),
        "excludes": _coerce_string_list(
            value.get("excludes"),
            field_label=f"{field_label}.excludes",
        ),
    }


def normalize_plan_item_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a persisted plan item payload."""

    if "id" not in data:
        raise ValueError("plan item id is required")
    if "order_key" not in data:
        raise ValueError("plan item order_key is required")
    if "title" not in data:
        raise ValueError("plan item title is required")

    kind = data.get("kind")
    if kind is None:
        raise ValueError("plan item kind is required")
    if kind not in ITEM_KINDS:
        raise ValueError(f"invalid plan item kind: {kind!r}")

    if "planning_status" not in data:
        raise ValueError("planning_status is required")
    planning_status = require_planning_status(data["planning_status"])
    superseded_by = require_optional_string(data.get("superseded_by"), "superseded_by")
    if planning_status == "superseded" and not superseded_by:
        raise ValueError("superseded items require superseded_by")
    if planning_status != "superseded" and superseded_by is not None:
        raise ValueError("superseded_by is only valid when planning_status is superseded")

    return {
        "id": require_string(data["id"], "plan item id"),
        "parent_id": require_optional_string(data.get("parent_id"), "parent_id"),
        "order_key": require_string(data["order_key"], "order_key"),
        "title": require_string(data["title"], "title"),
        "outcome": require_string(data.get("outcome", ""), "outcome"),
        "scope": require_scope_dict(data.get("scope"), field_label="scope"),
        "boundaries": _coerce_string_list(
            data.get("boundaries"),
            field_label="boundaries",
        ),
        "depends_on": _coerce_string_list(
            data.get("depends_on"),
            field_label="depends_on",
        ),
        "acceptance": _coerce_string_list(
            data.get("acceptance"),
            field_label="acceptance",
        ),
        "risks": _coerce_string_list(data.get("risks"), field_label="risks"),
        "source_refs": _coerce_string_list(
            data.get("source_refs"),
            field_label="source_refs",
        ),
        "planning_status": planning_status,
        "superseded_by": superseded_by,
        "kind": kind,
    }


def normalize_plan_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Validate schema v2 and coerce optional list fields to lists."""

    if "revision" not in data:
        raise ValueError("plan revision is required")

    validate_plan_schema_version(data)

    normalized = dict(data)
    normalized["schema_version"] = PLAN_SCHEMA_VERSION
    normalized["id"] = require_string(normalized.get("id"), "plan id")
    normalized["revision"] = require_non_negative_int(normalized["revision"], "revision")
    normalized["output_goal"] = require_string(
        normalized.get("output_goal", ""),
        "output_goal",
    )
    normalized["input_refs"] = _coerce_string_list(
        normalized.get("input_refs"),
        field_label="input_refs",
    )
    normalized["scope"] = require_scope_dict(normalized.get("scope"), field_label="plan scope")
    normalized["boundaries"] = _coerce_string_list(
        normalized.get("boundaries"),
        field_label="plan boundaries",
    )
    normalized["constraints"] = _coerce_string_list(
        normalized.get("constraints"),
        field_label="plan constraints",
    )
    normalized["assumptions"] = _coerce_string_list(
        normalized.get("assumptions"),
        field_label="plan assumptions",
    )
    normalized["acceptance"] = _coerce_string_list(
        normalized.get("acceptance"),
        field_label="plan acceptance",
    )
    normalized["risks"] = _coerce_string_list(
        normalized.get("risks"),
        field_label="plan risks",
    )

    raw_items = normalized.get("items")
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list):
        raise ValueError("plan items must be a list")

    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("each plan item must be an object")
        item = normalize_plan_item_payload(raw_item)
        if "depth" in raw_item:
            item["depth"] = require_non_negative_int(raw_item["depth"], "depth")
        items.append(item)
    normalized["items"] = items
    return normalized


__all__ = [
    "ITEM_KINDS",
    "PLANNING_STATUSES",
    "PLAN_SCHEMA_VERSION",
    "UNSUPPORTED_PLAN_SCHEMA_MESSAGE",
    "UnsupportedPlanSchemaVersionError",
    "normalize_plan_item_payload",
    "normalize_plan_payload",
    "require_int_not_bool",
    "require_non_negative_int",
    "require_optional_string",
    "require_planning_status",
    "require_scope_dict",
    "require_string",
    "validate_plan_schema_version",
]
