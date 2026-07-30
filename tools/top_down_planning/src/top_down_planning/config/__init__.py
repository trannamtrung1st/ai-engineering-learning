"""Configuration loading and CLI override resolution (proposal §14)."""

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG
from top_down_planning.config.errors import ConfigError
from top_down_planning.config.resolve import (
    apply_cli_overrides,
    compute_input_digest,
    compute_output_goal_digest,
    deep_merge,
    load_yaml_config,
    parse_override_value,
    resolve_config,
    set_nested_path,
)

__all__ = [
    "ALLOWED_OVERRIDE_PATHS",
    "DEFAULT_CONFIG",
    "ConfigError",
    "apply_cli_overrides",
    "compute_input_digest",
    "compute_output_goal_digest",
    "deep_merge",
    "load_yaml_config",
    "parse_override_value",
    "resolve_config",
    "set_nested_path",
]
