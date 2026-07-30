"""Minimal JSON Schema validation without external dependencies."""

from __future__ import annotations

from typing import Any


def validate_against_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
) -> list[str]:
    """Minimal JSON Schema checker for published contracts (no external deps)."""

    issues: list[str] = []

    if "oneOf" in schema:
        branch_issues = [
            validate_against_schema(value, branch, path=path)
            for branch in schema["oneOf"]
        ]
        if not any(not branch for branch in branch_issues):
            issues.append(f"{path}: value does not match any oneOf branch")
        return issues

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(schema.get("properties", {}))
            if extra:
                issues.append(f"{path}: unexpected properties: {sorted(extra)}")
        elif isinstance(schema.get("additionalProperties"), dict):
            allowed = set(schema.get("properties", {}))
            value_schema = schema["additionalProperties"]
            for key, item in value.items():
                item_path = f"{path}.{key}"
                if key in allowed:
                    continue
                issues.extend(
                    validate_against_schema(item, value_schema, path=item_path)
                )
        for key in schema.get("required", []):
            if key not in value:
                issues.append(f"{path}: missing required property {key!r}")
        for key, prop_schema in (schema.get("properties") or {}).items():
            if key in value:
                issues.extend(
                    validate_against_schema(value[key], prop_schema, path=f"{path}.{key}")
                )
        return issues

    if schema_type == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                issues.extend(
                    validate_against_schema(
                        item,
                        item_schema,
                        path=f"{path}[{index}]",
                    )
                )
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            issues.append(f"{path}: expected at least {min_items} items")
        return issues

    if schema_type == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string"]
        if "enum" in schema and value not in schema["enum"]:
            issues.append(f"{path}: value {value!r} not in enum")
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            issues.append(f"{path}: string shorter than minLength {min_length}")
        return issues

    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"{path}: expected integer"]
        return issues

    if schema_type == "boolean":
        if not isinstance(value, bool):
            return [f"{path}: expected boolean"]
        if "const" in schema and value != schema["const"]:
            issues.append(f"{path}: expected const {schema['const']!r}")
        return issues

    if isinstance(schema_type, list):
        if any(
            not validate_against_schema(value, {"type": option}, path=path)
            for option in schema_type
        ):
            return []
        return [f"{path}: expected one of types {schema_type}"]

    if "const" in schema and value != schema["const"]:
        issues.append(f"{path}: expected const {schema['const']!r}")

    return issues


__all__ = ["validate_against_schema"]
