"""Boolean parsing and CLI/environment/default precedence."""

from __future__ import annotations

import os

_TRUTHY = frozenset({"true", "1", "yes", "on", "t", "y"})
_FALSY = frozenset({"false", "0", "no", "off", "f", "n"})


def parse_optional_bool(value: str | None, *, name: str) -> bool | None:
    """Parse ``true|false`` strings; ``None`` means use the default."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise ValueError(f"Invalid value for {name}: {value!r} (expected true or false)")


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def resolve_precedence(
    *,
    cli_value: bool | None,
    profile_value: bool | None,
    default: bool,
) -> bool:
    if cli_value is not None:
        return cli_value
    if profile_value is not None:
        return profile_value
    return default
