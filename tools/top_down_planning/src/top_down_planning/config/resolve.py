"""TDP configuration resolution (proposal §14)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from core_tools.config import (
    apply_cli_overrides,
    compute_input_refs_digest,
    deep_merge,
    load_yaml_config,
)
from core_tools.config.errors import ConfigError
from core_tools.persistence.digests import digest_text

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG

__all__ = [
    "compute_input_digest",
    "compute_output_goal_digest",
    "resolve_config",
]


def _collect_leaf_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths |= _collect_leaf_paths(child, path)
        return paths
    return {prefix} if prefix else set()


def _reject_unknown_config_paths(
    config: dict[str, Any],
    *,
    allowed_paths: frozenset[str],
) -> None:
    unknown = sorted(_collect_leaf_paths(config) - allowed_paths)
    if unknown:
        raise ConfigError(f"unknown config path: {unknown[0]}", path=unknown[0])


def resolve_config(
    config_path: Path | None,
    overrides: list[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve configuration with precedence:
    built-in defaults < YAML configuration < CLI --set overrides.
    """

    resolved = copy.deepcopy(DEFAULT_CONFIG)
    if config_path is not None:
        yaml_config = load_yaml_config(config_path)
        _reject_unknown_config_paths(yaml_config, allowed_paths=ALLOWED_OVERRIDE_PATHS)
        resolved = deep_merge(resolved, yaml_config)
    if overrides:
        resolved = apply_cli_overrides(
            resolved,
            overrides,
            allowed_paths=ALLOWED_OVERRIDE_PATHS,
        )
    _reject_unknown_config_paths(resolved, allowed_paths=ALLOWED_OVERRIDE_PATHS)
    return resolved


def compute_input_digest(config: dict[str, Any], *, base_dir: Path) -> str:
    """Digest input references relative to the resolved workspace directory."""

    refs = list((config.get("run") or {}).get("input_refs") or [])
    return compute_input_refs_digest(refs, base_dir=base_dir)


def compute_output_goal_digest(config: dict[str, Any]) -> str:
    goal = str((config.get("run") or {}).get("output_goal") or "")
    return digest_text(goal)
