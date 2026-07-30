"""Generic configuration allowlist validation."""

from __future__ import annotations

from typing import Any

from core_tools.config.errors import ConfigError


def collect_leaf_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths |= collect_leaf_paths(child, path)
        return paths
    return {prefix} if prefix else set()


def reject_unknown_config_paths(
    config: dict[str, Any],
    *,
    allowed_paths: frozenset[str],
) -> None:
    unknown = sorted(collect_leaf_paths(config) - allowed_paths)
    if unknown:
        raise ConfigError(f"unknown config path: {unknown[0]}", path=unknown[0])
