"""Minimal YAML serialization for resolved-config.yaml (stdlib only)."""

from __future__ import annotations

from typing import Any


def dump_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return f"{prefix}{{}}"
        lines: list[str] = []
        for key, item in sorted(value.items()):
            rendered_key = _yaml_key(str(key))
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{rendered_key}:")
                lines.append(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}{rendered_key}: {_yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(value)}"


def _yaml_key(key: str) -> str:
    if key and key[0].isalpha() and all(ch.isalnum() or ch in "-_" for ch in key):
        return key
    return json_escape_key(key)


def json_escape_key(key: str) -> str:
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    if "\n" in escaped or ":" in escaped or escaped.startswith(("#", "-", "[", "{")):
        return f'"{escaped}"'
    return escaped
