"""Unit tests for configuration resolution and CLI overrides."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.user import handle_validate_command
from top_down_planning.config import (
    ConfigError,
    compute_input_digest,
    resolve_config,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_config_digest
from tests.conftest import run_cli
from tests.helpers import run_digests_for_config, whole_plan_approval_record, write_config


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

    assert compute_config_digest(base) != compute_config_digest(overridden)


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
            "review.whole_plan.required=false",
            "run.input_refs=[README.md, docs/spec.md]",
        ],
    )
    assert resolved["planning"]["max_depth"] == 5
    assert resolved["review"]["whole_plan"]["required"] is False
    assert resolved["run"]["input_refs"] == ["README.md", "docs/spec.md"]


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
        "provider": {"name": "stub"},
    }
    input_digest, output_goal_digest = run_digests_for_config(store.root, config)
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=input_digest,
        output_goal_digest=output_goal_digest,
        workspace=str(store.root),
    )


def test_cli_validate_reports_plan_issues(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-validate-issues"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    child = PlanItem(
        id="item-child",
        parent_id="item-root",
        order_key="0000000000",
        title="Child",
        depends_on=["item-missing"],
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
    run_id = "run-validate-approval"
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
