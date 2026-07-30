"""Unit tests for config allowlist validation."""

from __future__ import annotations

import pytest

from core_tools.config import ConfigError, collect_leaf_paths, reject_unknown_config_paths


def test_collect_leaf_paths_nested() -> None:
    config = {"a": {"b": 1}, "c": 2}
    assert collect_leaf_paths(config) == {"a.b", "c"}


def test_reject_unknown_config_paths() -> None:
    config = {"known": {"value": 1}, "unknown": 2}
    with pytest.raises(ConfigError, match="unknown config path"):
        reject_unknown_config_paths(
            config,
            allowed_paths=frozenset({"known.value"}),
        )
