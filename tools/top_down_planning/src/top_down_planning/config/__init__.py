"""Configuration loading and CLI override resolution (proposal §14)."""

from core_tools.config import ConfigError

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG
from top_down_planning.config.resolve import (
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
)

__all__ = [
    "ALLOWED_OVERRIDE_PATHS",
    "DEFAULT_CONFIG",
    "ConfigError",
    "compute_input_digest",
    "compute_output_goal_digest",
    "resolve_config",
]
