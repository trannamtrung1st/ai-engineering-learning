"""Unit tests for minimal JSON Schema validation."""

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
