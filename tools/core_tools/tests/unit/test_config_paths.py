"""Unit tests for workspace path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config import (
    ConfigError,
    assert_path_within_workspace,
    is_path_within_workspace,
    resolve_path,
    resolve_workspace,
    resolve_workspace_path,
)


def test_resolve_workspace_defaults_to_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    assert resolve_workspace({}, cwd=cwd) == cwd.resolve()


def test_resolve_workspace_relative_from_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    nested = cwd / "nested"
    nested.mkdir(parents=True)
    config = {"project": {"workspace": "nested"}}
    assert resolve_workspace(config, cwd=cwd) == nested.resolve()


def test_resolve_workspace_absolute_unchanged(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    absolute = tmp_path / "absolute-workspace"
    absolute.mkdir()
    config = {"project": {"workspace": str(absolute)}}
    assert resolve_workspace(config, cwd=cwd) == absolute.resolve()


def test_resolve_path_absolute_unchanged(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute"
    absolute.mkdir()
    assert resolve_path(absolute, cwd=tmp_path / "other") == absolute.resolve()


def test_resolve_workspace_path_relative(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "docs"
    nested.mkdir()
    assert resolve_workspace_path("docs", workspace=workspace) == nested.resolve()


def test_is_path_within_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    inside.write_text("x", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("y", encoding="utf-8")
    assert is_path_within_workspace(inside, workspace=workspace)
    assert not is_path_within_workspace(outside, workspace=workspace)


def test_assert_path_within_workspace_raises(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("y", encoding="utf-8")
    with pytest.raises(ConfigError, match="resolves outside project workspace"):
        assert_path_within_workspace(
            outside,
            workspace=workspace,
            field="resources",
            configured_value="../outside.txt",
        )
