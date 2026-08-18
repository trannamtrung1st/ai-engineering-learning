"""JSON Schema Draft 2020-12 subset used by published TDP contracts."""

from __future__ import annotations

import re
from typing import Any


def _type_names(schema_type: Any) -> list[str]:
    if schema_type is None:
        return []
    if isinstance(schema_type, list):
        return [str(item) for item in schema_type]
    return [str(schema_type)]


def _matches_json_type(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def validate_against_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
) -> list[str]:
    """Validate ``value`` against a published JSON Schema subset."""

    issues: list[str] = []

    if "oneOf" in schema:
        matching = 0
        for branch in schema["oneOf"]:
            if not validate_against_schema(value, branch, path=path):
                matching += 1
        if matching == 0:
            issues.append(f"{path}: value does not match any oneOf branch")
        elif matching > 1:
            issues.append(
                f"{path}: value matches {matching} oneOf branches; exactly one is required"
            )
        return issues

    if "anyOf" in schema:
        if not any(
            not validate_against_schema(value, branch, path=path)
            for branch in schema["anyOf"]
        ):
            issues.append(f"{path}: value does not match any anyOf branch")
        return issues

    schema_type = schema.get("type")
    type_names = _type_names(schema_type)
    if type_names and not any(_matches_json_type(value, name) for name in type_names):
        if len(type_names) == 1:
            return [f"{path}: expected {type_names[0]}"]
        return [f"{path}: expected one of types {type_names}"]

    if "const" in schema and value != schema["const"]:
        issues.append(f"{path}: expected const {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        issues.append(f"{path}: value {value!r} not in enum")

    if isinstance(value, dict):
        additional = schema.get("additionalProperties", True)
        properties = schema.get("properties") or {}
        if additional is False:
            extra = set(value) - set(properties)
            if extra:
                issues.append(f"{path}: unexpected properties: {sorted(extra)}")
        elif isinstance(additional, dict):
            for key, item in value.items():
                if key in properties:
                    continue
                issues.extend(
                    validate_against_schema(item, additional, path=f"{path}.{key}")
                )
        for key in schema.get("required", []):
            if key not in value:
                issues.append(f"{path}: missing required property {key!r}")
        min_properties = schema.get("minProperties")
        if min_properties is not None and len(value) < int(min_properties):
            issues.append(f"{path}: expected at least {min_properties} properties")
        max_properties = schema.get("maxProperties")
        if max_properties is not None and len(value) > int(max_properties):
            issues.append(f"{path}: expected at most {max_properties} properties")
        for key, prop_schema in properties.items():
            if key in value:
                issues.extend(
                    validate_against_schema(value[key], prop_schema, path=f"{path}.{key}")
                )

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                issues.extend(
                    validate_against_schema(item, item_schema, path=f"{path}[{index}]")
                )
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < int(min_items):
            issues.append(f"{path}: expected at least {min_items} items")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > int(max_items):
            issues.append(f"{path}: expected at most {max_items} items")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < int(min_length):
            issues.append(f"{path}: string shorter than minLength {min_length}")
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > int(max_length):
            issues.append(f"{path}: string longer than maxLength {max_length}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            issues.append(f"{path}: string does not match pattern {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            issues.append(f"{path}: value is below minimum {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            issues.append(f"{path}: value is above maximum {maximum}")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if exclusive_minimum is not None and value <= exclusive_minimum:
            issues.append(f"{path}: value is not above exclusiveMinimum {exclusive_minimum}")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if exclusive_maximum is not None and value >= exclusive_maximum:
            issues.append(f"{path}: value is not below exclusiveMaximum {exclusive_maximum}")

    return issues


__all__ = ["validate_against_schema"]
