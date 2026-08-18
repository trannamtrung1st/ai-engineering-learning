"""Unit tests for published JSON Schema keyword conformance."""

from __future__ import annotations

from core_tools.schema import validate_against_schema


def test_validate_object_required_fields() -> None:
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    assert validate_against_schema({"name": "ok"}, schema) == []
    issues = validate_against_schema({}, schema)
    assert any("missing required property 'name'" in issue for issue in issues)


def test_validate_string_enum() -> None:
    schema = {"type": "string", "enum": ["a", "b"]}
    assert validate_against_schema("a", schema) == []
    issues = validate_against_schema("c", schema)
    assert any("not in enum" in issue for issue in issues)


def test_validate_null_type_rejects_unrelated_values() -> None:
    schema = {"type": ["string", "null"]}
    assert validate_against_schema("ok", schema) == []
    assert validate_against_schema(None, schema) == []
    issues = validate_against_schema(123, schema)
    assert issues
    issues = validate_against_schema({"x": 1}, schema)
    assert issues


def test_validate_number_accepts_ints_and_floats_not_bools() -> None:
    schema = {"type": "number", "minimum": 0}
    assert validate_against_schema(1, schema) == []
    assert validate_against_schema(0.5, schema) == []
    assert validate_against_schema(-1, schema)
    assert validate_against_schema(True, schema)


def test_validate_max_items_and_max_length() -> None:
    array_schema = {"type": "array", "items": {"type": "string"}, "maxItems": 1}
    assert validate_against_schema(["a"], array_schema) == []
    assert validate_against_schema(["a", "b"], array_schema)
    string_schema = {"type": "string", "maxLength": 3}
    assert validate_against_schema("abc", string_schema) == []
    assert validate_against_schema("abcd", string_schema)


def test_validate_min_properties_and_pattern() -> None:
    object_schema = {
        "type": "object",
        "minProperties": 1,
        "properties": {"title": {"type": "string"}},
        "additionalProperties": False,
    }
    assert validate_against_schema({}, object_schema)
    assert validate_against_schema({"title": "ok"}, object_schema) == []
    pattern_schema = {"type": "string", "pattern": r"\S"}
    assert validate_against_schema("x", pattern_schema) == []
    assert validate_against_schema("   ", pattern_schema)


def test_oneof_requires_exactly_one_matching_branch() -> None:
    schema = {
        "oneOf": [
            {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
            {"type": "object", "required": ["b"], "properties": {"b": {"type": "string"}}},
        ]
    }
    assert validate_against_schema({"a": "x"}, schema) == []
    both = validate_against_schema({"a": "x", "b": "y"}, schema)
    assert both
    assert any("exactly one" in issue for issue in both)
