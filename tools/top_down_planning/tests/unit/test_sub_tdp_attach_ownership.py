"""Attach must not mutate parent state while another process owns the run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from top_down_planning.domain.run_ownership import RunOwnershipError
from tests.conftest import run_cli
from tests.helpers import accept_child_run, create_run_kwargs
from tests.support.run_builders import _parent_with_orchestration
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory


def test_sub_tdp_attach_rejects_live_parent_owner(tmp_path: Path) -> None:
    store, parent_id, package, _config = _parent_with_orchestration(tmp_path)
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute", "observability": {}},
    )
    accept_child_run(store, child_id)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nrun:\n  output_goal: Ship the product.\n",
        encoding="utf-8",
    )

    with patch(
        "top_down_planning.cli.sub_tdp.run_ownership",
        side_effect=RunOwnershipError("live owner", code="run_ownership_conflict"),
    ):
        result = run_cli(
            [
                "sub-tdp",
                "attach",
                "--parent",
                parent_id,
                "--child",
                child_id,
                "--config",
                str(config_path),
                "--runs-dir",
                str(tmp_path / "runs"),
                "--stream-json",
            ]
        )
    assert result.exit_code == 1
    payload = result.json()
    assert payload.get("ok") is False
    assert (payload.get("error") or {}).get("code") == "run_ownership_conflict"
