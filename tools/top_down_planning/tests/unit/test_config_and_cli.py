"""Unit tests for configuration resolution and CLI overrides."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from top_down_planning.cli.user import handle_validate_command
from top_down_planning.config import (
    ConfigError,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_config,
    resolve_output_goal_text,
    resolve_workspace,
)
from core_tools.persistence.digests import digest_text
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)
from tests.conftest import CliResult, run_cli
from tests.helpers import create_run_kwargs, run_digests_for_config, whole_plan_approval_record, write_config


def test_defaults_yaml_cli_precedence_changes_resolved_values(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        """
version: 1
run:
  output_goal: Deliver from YAML.
planning:
  max_depth: 3
""",
    )

    base = resolve_config(config_path)
    overridden = resolve_config(
        config_path,
        ["planning.max_depth=5", "limits.production.max_batches=80"],
    )

    assert base["planning"]["max_depth"] == 3
    assert overridden["planning"]["max_depth"] == 5
    assert overridden["limits"]["production"]["max_batches"] == 80
    assert overridden["run"]["output_goal"] == "Deliver from YAML."


def test_override_digest_changes_when_cli_set_applied(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        "run:\n  output_goal: Goal.\nplanning:\n  max_depth: 4\n",
    )
    base = resolve_config(config_path)
    overridden = resolve_config(config_path, ["planning.max_depth=5"])

    assert compute_config_contract_digest(base) != compute_config_contract_digest(overridden)
    assert compute_config_execution_digest(base) == compute_config_execution_digest(overridden)


def test_limit_only_override_changes_execution_digest_not_contract(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "base.yaml",
        "run:\n  output_goal: Goal.\nplanning:\n  max_depth: 4\n",
    )
    base = resolve_config(config_path)
    overridden = resolve_config(config_path, ["limits.production.max_batches=80"])

    assert compute_config_contract_digest(base) == compute_config_contract_digest(overridden)
    assert compute_config_execution_digest(base) != compute_config_execution_digest(overridden)


def test_unknown_override_path_fails_explicitly(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(config_path, ["foo.bar=1"])


def test_unknown_yaml_key_fails_explicitly(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "typo.yaml",
        "run:\n  output_goal: Goal.\nplannig:\n  max_depth: 3\n",
    )
    with pytest.raises(ConfigError, match="unknown config path"):
        resolve_config(config_path)


def test_override_values_parse_yaml_types(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "base.yaml", "run:\n  output_goal: Goal.\n")
    resolved = resolve_config(
        config_path,
        [
            "planning.max_depth=5",
            "review.focused_plan.enabled=false",
            "run.input_refs=[README.md, docs/guide.md]",
        ],
    )
    assert resolved["planning"]["max_depth"] == 5
    assert resolved["review"]["focused_plan"]["enabled"] is False
    assert resolved["run"]["input_refs"] == ["README.md", "docs/guide.md"]


def test_input_digest_uses_file_content_when_ref_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    readme = workspace / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = write_config(
        config_dir / "base.yaml",
        "run:\n  output_goal: Goal.\n  input_refs:\n    - README.md\n",
    )
    resolved = resolve_config(config_path)
    digest_once = compute_input_digest(resolved, base_dir=workspace)

    readme.write_text("beta", encoding="utf-8")
    digest_twice = compute_input_digest(resolved, base_dir=workspace)
    assert digest_once != digest_twice


def test_cli_unknown_set_override_exits_non_zero(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = write_config(
        config_dir / "run.yaml",
        "run:\n  output_goal: Deliver the sample output.\n",
    )
    result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--set",
            "foo.bar=1",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 2
    payload = result.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"


def _create_validate_run(
    store: FileRunStore,
    run_id: str,
    *,
    plan: Plan | None = None,
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    if plan is None:
        plan = Plan(
            id=f"plan-{run_id}",
            revision=0,
            output_goal="Deliver the sample output.",
            items={"item-root": root},
        )
    config = {
        "run": {"output_goal": "Deliver the sample output.", "input_refs": []},
        "planning": {"max_depth": 4, "max_expansion_per_item": 7},
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
    )


def test_cli_validate_reports_plan_issues(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002002-002002"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    child = PlanItem(
        id="item-child",
        parent_id="item-root",
        order_key="0000000000",
        title="Child",
        depends_on=["item-missing"],
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the sample output.",
        items={"item-root": root, "item-child": child},
    )
    _create_validate_run(store, run_id, plan=plan)

    with pytest.raises(SystemExit) as exit_info:
        handle_validate_command(
            Namespace(run=run_id, runs_dir=str(store.root), stream_json=True)
        )
    assert exit_info.value.code == 1


def test_validate_uses_approval_mode_when_whole_plan_review_approved(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002001-002001"
    _create_validate_run(store, run_id)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    with patch("top_down_planning.cli.user.emit_payload") as emit_payload:
        with pytest.raises(SystemExit) as exit_info:
            handle_validate_command(
                Namespace(run=run_id, runs_dir=str(store.root), stream_json=True)
            )
        assert exit_info.value.code == 0
        payload = emit_payload.call_args.args[0]
        assert payload["plan"]["mode"] == "approval"


def _workspace_with_goal_file(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    goal_file = workspace / "goals" / "output-goal.md"
    goal_file.parent.mkdir(parents=True)
    goal_file.write_text("Deliver from file.\n", encoding="utf-8")
    config = {
        "run": {
            "output_goal_file": "goals/output-goal.md",
            "input_refs": [],
        }
    }
    return workspace, goal_file, config


def test_resolve_output_goal_text_from_file(tmp_path: Path) -> None:
    workspace, goal_file, config = _workspace_with_goal_file(tmp_path)
    assert resolve_output_goal_text(config, base_dir=workspace) == "Deliver from file.\n"
    assert compute_output_goal_digest(config, base_dir=workspace) == digest_text(
        "Deliver from file.\n"
    )


def test_resolve_output_goal_text_absolute_path(tmp_path: Path) -> None:
    workspace, goal_file, config = _workspace_with_goal_file(tmp_path)
    config["run"]["output_goal_file"] = str(goal_file.resolve())
    assert resolve_output_goal_text(config, base_dir=workspace) == "Deliver from file.\n"


def test_resolve_output_goal_text_rejects_both_sources(tmp_path: Path) -> None:
    workspace, _, config = _workspace_with_goal_file(tmp_path)
    config["run"]["output_goal"] = "Inline goal."
    with pytest.raises(ConfigError, match="not both"):
        resolve_output_goal_text(config, base_dir=workspace)


def test_resolve_output_goal_text_requires_one_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = {"run": {"input_refs": []}}
    with pytest.raises(ConfigError, match="requires run.output_goal"):
        resolve_output_goal_text(config, base_dir=workspace)


def test_resolve_output_goal_text_rejects_missing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = {"run": {"output_goal_file": "missing.md", "input_refs": []}}
    with pytest.raises(ConfigError, match="not found"):
        resolve_output_goal_text(config, base_dir=workspace)


def test_resolve_output_goal_text_rejects_empty_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    goal_file = workspace / "empty.md"
    goal_file.write_text("   \n", encoding="utf-8")
    config = {"run": {"output_goal_file": "empty.md", "input_refs": []}}
    with pytest.raises(ConfigError, match="empty"):
        resolve_output_goal_text(config, base_dir=workspace)


def test_output_goal_file_resolves_from_workspace_not_config_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    config_dir = workspace / "temp" / "configs"
    config_dir.mkdir(parents=True)
    goal_file = workspace / "goals" / "output-goal.md"
    goal_file.parent.mkdir(parents=True)
    goal_file.write_text("Workspace-relative goal.", encoding="utf-8")
    config_path = write_config(
        config_dir / "run.yaml",
        """
project:
  workspace: .
run:
  output_goal_file: goals/output-goal.md
""",
    )
    resolved = resolve_config(config_path, cwd=workspace)
    base_dir = resolve_workspace(resolved, cwd=workspace)
    assert resolve_output_goal_text(resolved, base_dir=base_dir) == (
        "Workspace-relative goal."
    )


def test_file_backed_goal_leaves_no_inline_output_goal_in_resolved_config(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    config_dir = workspace / "configs"
    config_dir.mkdir(parents=True)
    goal_file = workspace / "goal.md"
    goal_file.write_text("Goal from file.", encoding="utf-8")
    config_path = write_config(
        config_dir / "run.yaml",
        """
project:
  workspace: .
run:
  output_goal_file: goal.md
""",
    )
    resolved = resolve_config(config_path, cwd=workspace)
    run_section = resolved["run"]
    assert "output_goal" not in run_section
    assert run_section["output_goal_file"] == "goal.md"
    assert resolve_output_goal_text(resolved, base_dir=workspace) == "Goal from file."


def test_cli_result_json_returns_last_object_when_stdout_has_multiple() -> None:
    result = CliResult(
        exit_code=0,
        stdout='{"first": true}\n{"run_id": "run-1", "status": "running"}\n',
        stderr="",
    )

    assert result.json() == {"run_id": "run-1", "status": "running"}
