"""Multi-layer smoke tests (config → CLI → orchestrator → persistence)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.persistence.path_ids import RUN_ID_PATTERN
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.conftest import run_cli
from tests.helpers import plan_apply_turn, write_config


@pytest.mark.integration
def test_run_command_smoke_with_stub_provider(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = write_config(
        config_dir / "run.yaml",
        """
run:
  output_goal: Deliver the sample output.
provider:
  name: stub
planning:
  max_depth: 4
""",
    )
    runs_dir = tmp_path / "runs"

    provider = StubProvider()
    provider.script_turn(
        plan_apply_turn(
            operations=[
                {
                    "op": "add_item",
                    "temp_id": "item-api",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "API", "outcome": "API exists."},
                },
                {
                    "op": "add_item",
                    "temp_id": "item-ui",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "UI", "outcome": "UI exists."},
                },
            ]
        )
    )

    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        run_result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--set",
                "planning.max_depth=5",
                "--runs-dir",
                str(runs_dir),
                "--stream-json",
            ]
        )

    assert run_result.exit_code == 0, run_result.stderr
    run_payload = run_result.json()
    assert run_payload["ok"] is True
    assert run_payload["phase"] == WHOLE_PLAN_REVIEW

    run_id = run_payload["run_id"]
    assert RUN_ID_PATTERN.fullmatch(run_id)
    status_result = run_cli(
        [
            "status",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert status_result.exit_code == 0, status_result.stderr
    status_payload = status_result.json()
    assert status_payload["ok"] is True
    assert status_payload["run"]["phase"] == WHOLE_PLAN_REVIEW
    assert status_payload["run"]["plan_revision"] == 1

    resolved_path = runs_dir / run_id / "resolved-config.yaml"
    assert resolved_path.exists()
    assert "max_depth: 5" in resolved_path.read_text(encoding="utf-8")

    store = FileRunStore(runs_dir)
    plan = store.load_plan_model(run_id)
    assert len(plan.items) == 3
