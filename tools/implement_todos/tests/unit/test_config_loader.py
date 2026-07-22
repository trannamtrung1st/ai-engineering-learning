"""Run config YAML loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from todos_tool.config_loader import DEFAULT_COMMIT_HINT, build_run_config, load_run_config_file
from todos_tool.errors import TodosToolError


def test_load_run_config_file_resolves_paths_relative_to_config(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    hint_path = tmp_path / "commit-hint.md"
    hint_path.write_text("Use `agent: fix:` for bug fixes.\n", encoding="utf-8")
    config_path.write_text(
        "\n".join(
            [
                "workspace: .",
                "todos_dir: backlog",
                "model: composer-2.5",
                f"commit_hint_file: {hint_path.name}",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_run_config_file(config_path)
    config = build_run_config(config_path=config_path)

    assert loaded.todos_dir == "backlog"
    assert loaded.model == "composer-2.5"
    assert config.workspace_root == tmp_path.resolve()
    assert config.todos_dir == "backlog"
    assert config.model == "composer-2.5"
    assert config.commit_hint == "Use `agent: fix:` for bug fixes."


def test_build_run_config_cli_overrides_config(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "workspace: .",
                "todos_dir: backlog",
                "model: composer-2.5",
                "commit_hint: from config",
            ]
        ),
        encoding="utf-8",
    )

    config = build_run_config(
        config_path=config_path,
        todos_dir="todos",
        model="gpt-test",
        commit_hint="from cli",
    )

    assert config.todos_dir == "todos"
    assert config.model == "gpt-test"
    assert config.commit_hint == "from cli"


def test_build_run_config_uses_default_commit_hint(tmp_path: Path) -> None:
    config = build_run_config(workspace=tmp_path)
    assert config.commit_hint == DEFAULT_COMMIT_HINT


def test_build_run_config_rejects_both_commit_hint_sources(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    config_path.write_text(
        "commit_hint: inline\ncommit_hint_file: ./hint.md\n",
        encoding="utf-8",
    )

    with pytest.raises(TodosToolError, match="commit_hint or commit_hint_file"):
        load_run_config_file(config_path)


def test_build_run_config_cli_rejects_both_commit_hint_sources(tmp_path: Path) -> None:
    hint_path = tmp_path / "hint.md"
    hint_path.write_text("custom hint", encoding="utf-8")

    with pytest.raises(TodosToolError, match="--commit-hint or --commit-hint-file"):
        build_run_config(
            workspace=tmp_path,
            commit_hint="inline",
            commit_hint_file=hint_path,
        )


def test_build_run_config_applies_config_without_cli_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "workspace: .",
                "todos_dir: backlog",
                "model: composer-2.5",
                "commit_hint: from config only",
            ]
        ),
        encoding="utf-8",
    )

    config = build_run_config(config_path=config_path)

    assert config.workspace_root == tmp_path.resolve()
    assert config.todos_dir == "backlog"
    assert config.model == "composer-2.5"
    assert config.commit_hint == "from config only"


def test_build_run_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    config_path.write_text("unknown: true\n", encoding="utf-8")

    with pytest.raises(TodosToolError, match="Unknown config keys"):
        load_run_config_file(config_path)


def test_build_run_config_loads_force_reset_from_config(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    config_path.write_text("force_reset: true\n", encoding="utf-8")

    loaded = load_run_config_file(config_path)
    config = build_run_config(config_path=config_path)

    assert loaded.force_reset is True
    assert config.force_reset is True


def test_build_run_config_cli_overrides_force_reset(tmp_path: Path) -> None:
    config_path = tmp_path / "run.config.yaml"
    config_path.write_text("force_reset: false\n", encoding="utf-8")

    config = build_run_config(config_path=config_path, force_reset=True)

    assert config.force_reset is True
