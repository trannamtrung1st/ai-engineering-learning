"""Minimal YAML serialization for resolved-config.yaml (stdlib only)."""

from __future__ import annotations

import re
from typing import Any


def _strip_inline_comment(raw: str) -> str:
    """Drop unquoted ``#`` comments while keeping hashes inside quoted scalars."""

    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return raw[:index].rstrip()
    return raw


def load_yaml(text: str) -> Any:
    """Parse a small YAML subset used for resolved config and agent requests."""

    lines = text.splitlines()
    if not any(line.strip() and not line.strip().startswith("#") for line in lines):
        return {}

    def next_non_empty(start: int) -> int:
        current = start
        while current < len(lines):
            stripped = lines[current].strip()
            if stripped and not stripped.startswith("#"):
                return current
            current += 1
        return current

    def count_indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def parse_scalar(raw: str) -> Any:
        value = _strip_inline_comment(raw.strip())
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

    def parse_block_scalar(start: int, indent: int, *, folded: bool) -> tuple[str, int]:
        """Parse a ``>`` (folded) or ``|`` (literal) block scalar body."""

        # Prefer the first content line's indentation when deeper than ``indent``.
        index = start
        block_indent = indent
        probe = start
        while probe < len(lines):
            line = lines[probe]
            if line.strip():
                line_indent = count_indent(line)
                if line_indent < indent:
                    break
                block_indent = line_indent
                break
            probe += 1

        chunks: list[str] = []
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                chunks.append("")
                index += 1
                continue
            if count_indent(line) < block_indent:
                break
            chunks.append(line[block_indent:] if len(line) >= block_indent else line.lstrip(" "))
            index += 1

        if folded:
            # Fold non-empty lines with spaces; preserve blank-line paragraph breaks.
            parts: list[str] = []
            paragraph: list[str] = []
            for chunk in chunks:
                if chunk == "":
                    if paragraph:
                        parts.append(" ".join(paragraph))
                        paragraph = []
                    parts.append("")
                else:
                    paragraph.append(chunk.rstrip())
            if paragraph:
                parts.append(" ".join(paragraph))
            text = "\n".join(parts).strip("\n")
            return text, index
        return "\n".join(chunks).rstrip("\n"), index

    def parse_inline_mapping_item(content: str, start: int, indent: int) -> tuple[dict[str, Any], int] | None:
        """Parse ``- key: value`` (optionally followed by more indented keys)."""

        if ":" not in content:
            return None
        if content.startswith("{") or content.startswith("["):
            return None
        if content[0] in {'"', "'"}:
            return None

        key, remainder = content.split(":", 1)
        key = key.strip().strip('"')
        if not key or any(ch.isspace() for ch in key):
            return None
        remainder = remainder.strip()

        item: dict[str, Any] = {}
        index = start
        if remainder in {">", "|"}:
            index += 1
            block_text, index = parse_block_scalar(
                index,
                indent + 2,
                folded=remainder == ">",
            )
            item[key] = block_text
        elif remainder:
            item[key] = parse_scalar(remainder)
            index += 1
        else:
            index += 1
            index = next_non_empty(index)
            if index >= len(lines) or count_indent(lines[index]) <= indent:
                item[key] = {}
            else:
                child, index = parse_block(index, indent + 2)
                item[key] = child if child is not None else {}

        # Additional keys for the same list item, indented under the dash line.
        while index < len(lines):
            index = next_non_empty(index)
            if index >= len(lines):
                break
            line = lines[index]
            line_indent = count_indent(line)
            if line_indent <= indent:
                break
            if line_indent != indent + 2:
                break
            stripped_line = line.strip()
            if stripped_line.startswith("-") or ":" not in stripped_line:
                break
            extra_key, extra_remainder = stripped_line.split(":", 1)
            extra_key = extra_key.strip().strip('"')
            extra_remainder = extra_remainder.strip()
            if extra_remainder in {">", "|"}:
                index += 1
                block_text, index = parse_block_scalar(
                    index,
                    indent + 4,
                    folded=extra_remainder == ">",
                )
                item[extra_key] = block_text
            elif extra_remainder:
                item[extra_key] = parse_scalar(extra_remainder)
                index += 1
            else:
                index += 1
                index = next_non_empty(index)
                if index >= len(lines) or count_indent(lines[index]) <= indent + 2:
                    item[extra_key] = {}
                else:
                    child, index = parse_block(index, indent + 4)
                    item[extra_key] = child if child is not None else {}
        return item, index

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
            if remainder in {">", "|"}:
                index += 1
                block_text, index = parse_block_scalar(
                    index,
                    indent + 2,
                    folded=remainder == ">",
                )
                mapping[key] = block_text
                continue
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
                inline = parse_inline_mapping_item(content, index, indent)
                if inline is not None:
                    item, index = inline
                    items.append(item)
                    continue
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
    raw = str(value)
    escaped = (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    if (
        "\n" in raw
        or "\r" in raw
        or ":" in raw
        or raw.startswith(("#", "-", "[", "{"))
        or raw != escaped
    ):
        return f'"{escaped}"'
    return escaped
