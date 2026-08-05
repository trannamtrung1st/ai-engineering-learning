"""Tests for execution.mode configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config.errors import ConfigError
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.config.execution import EXECUTION_MODE_SINGLE, execution_mode_from_config
from top_down_planning.config.resolve import resolve_config


def test_default_execution_mode_is_single() -> None:
    assert execution_mode_from_config(DEFAULT_CONFIG) == EXECUTION_MODE_SINGLE


def test_resolve_config_rejects_sub_tdps_execution_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        "version: 1\n"
        "runtime:\n  runs_dir: .tdp/runs\n"
        "project:\n  workspace: .\n"
        "run:\n  output_goal: Goal.\n"
        "execution:\n  mode: sub_tdps\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="execution.mode"):
        resolve_config(config_path, cwd=tmp_path)


def test_resolve_config_rejects_invalid_execution_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        "version: 1\n"
        "runtime:\n  runs_dir: .tdp/runs\n"
        "project:\n  workspace: .\n"
        "run:\n  output_goal: Goal.\n"
        "execution:\n  mode: parallel\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="execution.mode"):
        resolve_config(config_path, cwd=tmp_path)
