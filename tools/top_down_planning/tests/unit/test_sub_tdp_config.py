"""Tests for execution.mode configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config.errors import ConfigError
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.config.execution import (
    EXECUTION_MODE_SINGLE,
    EXECUTION_MODE_SUB_TDPS,
    assert_child_execution_allowed,
    execution_mode_from_config,
    is_sub_tdps_mode,
)
from top_down_planning.config.resolve import resolve_config
from top_down_planning.persistence.digests import compute_config_contract_digest


def test_default_execution_mode_is_single() -> None:
    assert execution_mode_from_config(DEFAULT_CONFIG) == EXECUTION_MODE_SINGLE
    assert not is_sub_tdps_mode(DEFAULT_CONFIG)


def test_resolve_config_accepts_execution_mode_sub_tdps(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        "version: 1\n"
        "runtime:\n  runs_dir: .tdp/runs\n"
        "project:\n  workspace: .\n"
        "run:\n  output_goal: Goal.\n"
        "execution:\n  mode: sub_tdps\n",
        encoding="utf-8",
    )
    resolved = resolve_config(config_path, cwd=tmp_path)
    assert execution_mode_from_config(resolved) == EXECUTION_MODE_SUB_TDPS
    assert is_sub_tdps_mode(resolved)


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


def test_execution_mode_in_config_contract_digest() -> None:
    single = dict(DEFAULT_CONFIG)
    sub_tdps = dict(DEFAULT_CONFIG)
    sub_tdps["execution"] = {"mode": EXECUTION_MODE_SUB_TDPS}
    assert compute_config_contract_digest(single) != compute_config_contract_digest(sub_tdps)


def test_child_sub_tdps_mode_rejected_at_create_run() -> None:
    config = dict(DEFAULT_CONFIG)
    config["execution"] = {"mode": EXECUTION_MODE_SUB_TDPS}
    with pytest.raises(ConfigError, match="sub_tdps"):
        assert_child_execution_allowed(config)
