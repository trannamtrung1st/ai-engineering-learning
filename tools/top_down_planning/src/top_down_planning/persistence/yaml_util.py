"""Minimal YAML serialization for resolved-config.yaml (stdlib only)."""

from __future__ import annotations

import re
from typing import Any


def load_yaml(text: str) -> Any:
    """Parse a small YAML subset used for resolved config and agent requests."""

    lines = text.splitlines()
    if not any(line.strip() and not line.strip().startswith("#") for line in lines):
        return {}

    def next_non_empty(start: int) -> int:
        current = start
        while current < len(lines) and not lines[current].strip():
            current += 1
        return current

    def count_indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def parse_scalar(raw: str) -> Any:
        value = raw.strip()
        if not value:
            raise ValueError("empty scalar value")
        if value in {"null", "~"}:
            return None
        if value == "true":
            return True
        if value == "false":
            return False
        if value == "{}":
            return {}
        if value == "[]":
            return []
        if value.startswith('"') and value.endswith('"'):
            return (
                value[1:-1]
                .replace('\\"', '"')
                .replace("\\\\", "\\")
                .replace("\\n", "\n")
            )
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
        return value

    def parse_block(start: int, indent: int) -> tuple[Any, int]:
        index = next_non_empty(start)
        if index >= len(lines):
            return None, index

        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("- "):
            return parse_sequence(index, indent)
        if stripped == "-":
            return parse_sequence(index, indent)
        return parse_mapping(index, indent)

    def parse_mapping(start: int, indent: int) -> tuple[dict[str, Any], int]:
        mapping: dict[str, Any] = {}
        index = start
        while index < len(lines):
            index = next_non_empty(index)
            if index >= len(lines):
                break
            line = lines[index]
            if count_indent(line) < indent:
                break
            if count_indent(line) > indent:
                raise ValueError(f"unexpected indentation at line {index + 1}")

            stripped = line.strip()
            if stripped.startswith("- "):
                break
            if ":" not in stripped:
                raise ValueError(f"expected mapping entry at line {index + 1}")

            key, remainder = stripped.split(":", 1)
            key = key.strip().strip('"')
            remainder = remainder.strip()
            if remainder:
                mapping[key] = parse_scalar(remainder)
                index += 1
                continue

            index += 1
            index = next_non_empty(index)
            if index >= len(lines) or count_indent(lines[index]) <= indent:
                mapping[key] = {}
                continue

            child, index = parse_block(index, indent + 2)
            mapping[key] = child if child is not None else {}

        return mapping, index

    def parse_sequence(start: int, indent: int) -> tuple[list[Any], int]:
        items: list[Any] = []
        index = start
        while index < len(lines):
            index = next_non_empty(index)
            if index >= len(lines):
                break
            line = lines[index]
            if count_indent(line) < indent:
                break
            if count_indent(line) > indent:
                raise ValueError(f"unexpected indentation at line {index + 1}")

            stripped = line.strip()
            if not stripped.startswith("-"):
                break

            content = stripped[1:].strip()
            if content:
                items.append(parse_scalar(content))
                index += 1
                continue

            index += 1
            index = next_non_empty(index)
            if index >= len(lines) or count_indent(lines[index]) <= indent:
                items.append({})
                continue

            child, index = parse_block(index, indent + 2)
            items.append(child if child is not None else {})

        return items, index

    index = next_non_empty(0)
    if index >= len(lines):
        return {}
    if lines[index].strip().startswith("-"):
        value, _ = parse_sequence(index, count_indent(lines[index]))
        return value
    value, _ = parse_mapping(index, count_indent(lines[index]))
    return value

def dump_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return f"{prefix}{{}}"
        lines: list[str] = []
        for key, item in sorted(value.items()):
            rendered_key = _yaml_key(str(key))
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}{rendered_key}: {{}}")
                else:
                    lines.append(f"{prefix}{rendered_key}:")
                    lines.append(dump_yaml(item, indent + 2))
            elif isinstance(item, list):
                if not item:
                    lines.append(f"{prefix}{rendered_key}: []")
                else:
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
