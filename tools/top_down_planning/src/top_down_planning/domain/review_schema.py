"""Strict parsing helpers for persisted review evidence."""

from __future__ import annotations

from typing import Any

OUTPUT_RECORD_KINDS = frozenset(
    {
        "batch",
        "output",
        "contribution",
        "evidence",
        "disposition",
        "completion_claim",
        "traceability",
    }
)


def require_bool(value: Any, field_label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_label} must be a boolean")
    return value


def require_exact_string(value: Any, field_label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_label} must be a string")
    return value


def require_non_empty_string(value: Any, field_label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_label} must be a non-empty string")
    return value.strip()


def require_optional_exact_string(value: Any, field_label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_label} must be a string or null")
    stripped = value.strip()
    return stripped or None


def require_non_negative_int(value: Any, field_label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_label} must be an integer")
    if value < 0:
        raise ValueError(f"{field_label} must be non-negative")
    return value


def require_optional_non_negative_int(value: Any, field_label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_label} must be an integer or null")
    if value < 0:
        raise ValueError(f"{field_label} must be non-negative")
    return value


def require_string_list(
    value: Any,
    field_label: str,
    *,
    drop_empty: bool = False,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_label} must be a list")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_label}[{index}] must be a string")
        if drop_empty:
            stripped = item.strip()
            if stripped:
                normalized.append(stripped)
        else:
            normalized.append(item)
    return normalized


def require_output_record_kind(value: Any, field_label: str) -> str:
    record_kind = require_non_empty_string(value, field_label)
    if record_kind not in OUTPUT_RECORD_KINDS:
        raise ValueError(
            f"{field_label} must be one of: {', '.join(sorted(OUTPUT_RECORD_KINDS))}"
        )
    return record_kind


__all__ = [
    "OUTPUT_RECORD_KINDS",
    "require_bool",
    "require_exact_string",
    "require_non_empty_string",
    "require_non_negative_int",
    "require_optional_exact_string",
    "require_optional_non_negative_int",
    "require_output_record_kind",
    "require_string_list",
]
