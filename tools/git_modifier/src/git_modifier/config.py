"""Minimal YAML loader for flat git_modifier config files (no PyYAML required)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    lowered = value.lower()
    if lowered in ("null", "~", ""):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        return int(value)
    except ValueError:
        return value


def load_flat_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = _strip_inline_comment(line).strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        data[key.strip()] = _parse_scalar(raw_value)

    return data
