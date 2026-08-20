"""Unit tests for generic config helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config import (
    ConfigError,
    apply_cli_overrides,
    deep_merge,
    parse_override_value,
    set_nested_path,
)


def test_deep_merge_nested_dicts() -> None:
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    overlay = {"a": {"b": 9}, "e": 4}
    merged = deep_merge(base, overlay)
    assert merged == {"a": {"b": 9, "c": 2}, "d": 3, "e": 4}


def test_parse_override_value_yaml_types() -> None:
    assert parse_override_value("true") is True
    assert parse_override_value("5") == 5
    assert parse_override_value("[a, b]") == ["a", "b"]


def test_parse_override_value_keeps_unquoted_hash_in_scalar() -> None:
    assert parse_override_value("issue#123") == "issue#123"
    assert parse_override_value("abc # comment") == "abc"
    assert parse_override_value('"abc # literal"') == "abc # literal"
    assert parse_override_value('"https://example.test/page#section"') == (
        "https://example.test/page#section"
    )


def test_set_nested_path_rejects_unknown_when_allowed_paths_set() -> None:
    config: dict[str, object] = {}
    with pytest.raises(ConfigError, match="unknown config path"):
        set_nested_path(config, "foo.bar", 1, allowed_paths=frozenset({"known.path"}))


def test_apply_cli_overrides(tmp_path: Path) -> None:
    config = {"planning": {"max_depth": 3}}
    updated = apply_cli_overrides(
        config,
        ["planning.max_depth=5"],
        allowed_paths=frozenset({"planning.max_depth"}),
    )
    assert updated["planning"]["max_depth"] == 5
