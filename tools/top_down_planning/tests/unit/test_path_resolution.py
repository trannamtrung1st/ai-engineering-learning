"""Unit tests for cwd-based config path resolution."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.common import resolve_runs_dir
from top_down_planning.cli.user import handle_status_command
from top_down_planning.config import (
    compute_input_digest,
    resolve_config,
    resolve_path,
    resolve_workspace,
)
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import script_planning_candidate_ready, write_config


def _repo_layout(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    config_dir = repo / "configs"
    tools_dir = repo / "tools" / "top_down_planning"
    config_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    readme = tools_dir / "README.md"
    readme.write_text("tool readme", encoding="utf-8")
    task = config_dir / "task.md"
    task.write_text("task brief", encoding="utf-8")

    config_path = write_config(
        config_dir / "my-project.yaml",
        """
runtime:
  runs_dir: .tdp/runs
project:
  workspace: .
run:
  input_refs:
    - tools/top_down_planning/README.md
    - configs/task.md
  output_goal: Deliver docs.
provider:
  name: stub
""",
    )
    return {
        "repo": repo,
        "config_path": config_path,
        "readme": readme,
        "task": task,
    }


def test_resolve_workspace_defaults_to_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    config = resolve_config(None, cwd=cwd)
    assert resolve_workspace(config, cwd=cwd) == cwd.resolve()


def test_resolve_workspace_relative_from_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    nested = cwd / "nested"
    nested.mkdir(parents=True)
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
project:
  workspace: nested
run:
  output_goal: Goal.
""",
        ),
        cwd=cwd,
    )
    assert resolve_workspace(config, cwd=cwd) == nested.resolve()


def test_resolve_workspace_absolute_unchanged(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    absolute = tmp_path / "absolute-workspace"
    absolute.mkdir()
    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            f"""
project:
  workspace: {absolute}
run:
  output_goal: Goal.
""",
        )
    )
    assert resolve_workspace(config, cwd=cwd) == absolute.resolve()


def test_config_parent_does_not_affect_resolved_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _repo_layout(tmp_path)
    repo = layout["repo"]
    config_path = layout["config_path"]
    monkeypatch.chdir(repo)

    resolved = resolve_config(config_path)
    workspace = resolve_workspace(resolved, cwd=repo)
    runs = resolve_runs_dir(
        config_value=resolved["runtime"]["runs_dir"],
        cwd=repo,
        environ={},
    )

    assert config_path.resolve() == repo / "configs" / "my-project.yaml"
    assert workspace == repo.resolve()
    assert runs.path == (repo / ".tdp" / "runs").resolve()
    assert runs.source == "config"

    digest = compute_input_digest(resolved, base_dir=workspace)
    assert digest
    assert (workspace / "tools" / "top_down_planning" / "README.md").is_file()
    assert (workspace / "configs" / "task.md").is_file()

    config_parent_digest = compute_input_digest(
        resolved,
        base_dir=config_path.parent,
    )
    assert digest != config_parent_digest


def test_run_uses_cwd_workspace_not_config_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _repo_layout(tmp_path)
    repo = layout["repo"]
    config_path = layout["config_path"]
    runs_root = repo / ".tdp" / "runs"
    monkeypatch.chdir(repo)

    with patch("top_down_planning.cli.user.create_provider") as create_provider:
        from core_tools.provider import StubProvider

        provider = StubProvider()
        script_planning_candidate_ready(provider, text="done")
        create_provider.return_value = provider

        result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--stream-json",
            ],
        )

    assert result.exit_code == 0, result.stderr
    payload = result.json()
    assert payload["working_directory"] == str(repo.resolve())
    assert payload["config_file"] == str(config_path.resolve())
    assert payload["workspace"] == str(repo.resolve())
    assert payload["runs_root"] == str(runs_root.resolve())
    assert payload["runs_root_source"] == "config"

    run_id = payload["run_id"]
    run_record = FileRunStore(runs_root).load_run(run_id)
    assert run_record["workspace"] == str(repo.resolve())

    create_provider.assert_called_once()
    call_kwargs = create_provider.call_args.kwargs
    assert call_kwargs["workspace"] == repo.resolve()
    assert call_kwargs["extra_env"]["TDP_RUNS_DIR"] == str(runs_root.resolve())


def test_run_without_run_workspace_defaults_to_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "nested" / "cfg"
    config_dir.mkdir(parents=True)
    config_path = write_config(
        config_dir / "run.yaml",
        """
run:
  output_goal: Deliver output.
provider:
  name: stub
runtime:
  runs_dir: custom-runs
""",
    )

    with patch("top_down_planning.cli.user.create_provider") as create_provider:
        from core_tools.provider import StubProvider

        provider = StubProvider()
        script_planning_candidate_ready(provider, text="done")
        create_provider.return_value = provider

        result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--stream-json",
            ],
        )

    assert result.exit_code == 0, result.stderr
    payload = result.json()
    assert payload["workspace"] == str(tmp_path.resolve())
    create_provider.assert_called_once()
    assert create_provider.call_args.kwargs["workspace"] == tmp_path.resolve()


def test_resume_with_config_uses_cwd_runs_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _repo_layout(tmp_path)
    repo = layout["repo"]
    config_path = layout["config_path"]
    runs_root = repo / ".tdp" / "runs"
    monkeypatch.chdir(repo)

    with patch("top_down_planning.cli.user.create_provider") as create_provider:
        from core_tools.provider import StubProvider

        provider = StubProvider()
        script_planning_candidate_ready(provider, text="done")
        create_provider.return_value = provider

        run_result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--stream-json",
            ],
        )
    assert run_result.exit_code == 0, run_result.stderr
    run_id = run_result.json()["run_id"]

    with pytest.raises(SystemExit) as exc:
        handle_status_command(
            Namespace(
                run=run_id,
                runs_dir=None,
                config=str(config_path),
                stream_json=True,
            )
        )
    assert exc.value.code == 0
    assert (runs_root / run_id / "run.json").exists()


def test_absolute_workspace_config_remains_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    absolute = tmp_path / "absolute-workspace"
    absolute.mkdir()
    config_path = write_config(
        tmp_path / "run.yaml",
        f"""
project:
  workspace: {absolute}
run:
  output_goal: Deliver output.
provider:
  name: stub
runtime:
  runs_dir: custom-runs
""",
    )

    with patch("top_down_planning.cli.user.create_provider") as create_provider:
        from core_tools.provider import StubProvider

        provider = StubProvider()
        script_planning_candidate_ready(provider, text="done")
        create_provider.return_value = provider

        result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--stream-json",
            ],
        )

    assert result.exit_code == 0, result.stderr
    payload = result.json()
    assert payload["workspace"] == str(absolute.resolve())


def test_resolve_path_absolute_unchanged(tmp_path: Path) -> None:
    absolute = tmp_path / "abs"
    absolute.mkdir()
    assert resolve_path(absolute, cwd=tmp_path / "other") == absolute.resolve()

