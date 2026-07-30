"""Unit tests for run-store resolution and runtime.runs_dir configuration."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.common import resolve_runs_dir, runs_dir_config_value
from top_down_planning.cli.user import handle_status_command
from top_down_planning.config import resolve_config
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_config_digest
from tests.conftest import run_cli
from tests.helpers import write_config


def test_cli_overrides_environment_and_config(tmp_path: Path) -> None:
    resolved = resolve_runs_dir(
        explicit=str(tmp_path / "cli"),
        config_value=".tdp/runs",
        cwd=tmp_path,
        environ={"TDP_RUNS_DIR": str(tmp_path / "env")},
    )
    assert resolved.path == (tmp_path / "cli").resolve()
    assert resolved.source == "cli"


def test_environment_overrides_config(tmp_path: Path) -> None:
    resolved = resolve_runs_dir(
        config_value=".tdp/runs",
        cwd=tmp_path,
        environ={"TDP_RUNS_DIR": str(tmp_path / "env")},
    )
    assert resolved.path == (tmp_path / "env").resolve()
    assert resolved.source == "environment"


def test_config_overrides_default(tmp_path: Path) -> None:
    resolved = resolve_runs_dir(
        config_value=".tdp/runs",
        cwd=tmp_path,
        environ={},
    )
    assert resolved.path == (tmp_path / ".tdp" / "runs").resolve()
    assert resolved.source == "config"


def test_default_is_cwd_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    resolved = resolve_runs_dir(environ={})
    assert resolved.path == (tmp_path / "runs").resolve()
    assert resolved.source == "default"


def test_relative_config_value_resolves_against_cwd(tmp_path: Path) -> None:
    resolved = resolve_runs_dir(
        config_value="nested/store",
        cwd=tmp_path / "work",
        environ={},
    )
    assert resolved.path == (tmp_path / "work" / "nested" / "store").resolve()


def test_absolute_config_value_stays_absolute(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute-runs"
    resolved = resolve_runs_dir(
        config_value=str(absolute),
        cwd=tmp_path / "other",
        environ={},
    )
    assert resolved.path == absolute.resolve()


def test_set_runtime_runs_dir_override(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
runtime:
  runs_dir: .tdp/runs
""",
    )
    resolved = resolve_config(config_path, ["runtime.runs_dir=.tmp/custom"])
    assert runs_dir_config_value(resolved) == ".tmp/custom"


def test_run_requires_explicit_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = write_config(
        config_dir / "run.yaml",
        """
run:
  output_goal: Deliver output.
provider:
  name: stub
""",
    )

    result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--stream-json",
        ],
    )
    assert result.exit_code == 2
    payload = result.json()
    assert payload["error"]["code"] == "missing_runs_dir"


def test_run_creation_writes_to_resolved_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
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
    runs_root = tmp_path / "custom-runs"

    with patch("top_down_planning.cli.user.create_provider") as create_provider:
        from core_tools.provider import StubProvider

        provider = StubProvider()
        provider.script_turn(
            [
                {"type": "assistant", "text": "done"},
                {
                    "type": "done",
                    "subtype": "success",
                    "text": "done",
                    "is_error": False,
                    "signal": "candidate_plan_ready",
                },
            ]
        )
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
    run_id = payload["run_id"]
    assert payload["runs_root"] == str(runs_root.resolve())
    assert payload["runs_root_source"] == "config"
    assert (runs_root / run_id / "run.json").exists()
    run_store = FileRunStore(runs_root)
    invocation = run_store.load_invocation(run_id)
    assert invocation["runs_dir"]["path"] == str(runs_root.resolve())
    assert invocation["runs_dir"]["source"] == "config"


def test_read_only_status_does_not_create_missing_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
runtime:
  runs_dir: missing-store
""",
    )
    missing_store = tmp_path / "missing-store"
    assert not missing_store.exists()

    with pytest.raises(SystemExit) as exc:
        handle_status_command(
            Namespace(
                run="run-abc",
                runs_dir=None,
                config=str(config_path),
                stream_json=False,
            )
        )
    assert exc.value.code == 1
    assert not missing_store.exists()


def test_missing_run_error_includes_resolved_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    config_path = write_config(
        tmp_path / "base.yaml",
        """
run:
  output_goal: Goal.
runtime:
  runs_dir: runs
""",
    )

    with pytest.raises(SystemExit) as exc:
        handle_status_command(
            Namespace(
                run="run-missing",
                runs_dir=None,
                config=str(config_path),
                stream_json=False,
            )
        )
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert f"runs root: {runs_root.resolve()}" in captured.err


def test_environment_overrides_default_without_yaml_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TDP_RUNS_DIR", str(tmp_path / "from-env"))
    resolved = resolve_runs_dir()
    assert resolved.path == (tmp_path / "from-env").resolve()
    assert resolved.source == "environment"


def test_store_metadata_does_not_affect_config_digest(tmp_path: Path) -> None:
    no_runtime = write_config(
        tmp_path / "no-runtime.yaml",
        "run:\n  output_goal: Goal.\n",
    )
    with_runtime = write_config(
        tmp_path / "with-runtime.yaml",
        """
run:
  output_goal: Goal.
runtime:
  runs_dir: .tdp/runs
""",
    )
    assert compute_config_digest(resolve_config(no_runtime)) == compute_config_digest(
        resolve_config(with_runtime)
    )


def test_create_provider_receives_tdp_runs_dir_env(tmp_path: Path) -> None:
    from top_down_planning.cli.common import ResolvedRunsDir
    from top_down_planning.cli.user import _create_provider_for_run

    config = {"provider": {"name": "cursor", "skip_probe": True}}
    runs_path = tmp_path / "runs-store"
    resolved_runs = ResolvedRunsDir(runs_path.resolve(), "config")

    with patch("top_down_planning.cli.user.create_provider") as create_provider:
        _create_provider_for_run(
            config,
            workspace=tmp_path,
            resolved_runs=resolved_runs,
        )

    create_provider.assert_called_once_with(
        config,
        workspace=tmp_path,
        extra_env={"TDP_RUNS_DIR": str(runs_path.resolve())},
        on_provider_event=None,
    )
