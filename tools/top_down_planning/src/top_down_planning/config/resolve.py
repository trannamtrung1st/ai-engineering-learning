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
from core_tools.persistence.digests import digest_text

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG

__all__ = [
    "compute_input_digest",
    "compute_output_goal_digest",
    "resolve_config",
]


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
        resolved = deep_merge(resolved, load_yaml_config(config_path))
    if overrides:
        resolved = apply_cli_overrides(
            resolved,
            overrides,
            allowed_paths=ALLOWED_OVERRIDE_PATHS,
        )
    return resolved


def compute_input_digest(config: dict[str, Any], *, base_dir: Path) -> str:
    """Digest input references relative to the config file directory."""

    refs = list((config.get("run") or {}).get("input_refs") or [])
    return compute_input_refs_digest(refs, base_dir=base_dir)


def compute_output_goal_digest(config: dict[str, Any]) -> str:
    goal = str((config.get("run") or {}).get("output_goal") or "")
    return digest_text(goal)
