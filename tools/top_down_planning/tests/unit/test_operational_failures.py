"""Tests for operational failure handling (proposal §15)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.cli.user import handle_resume_command
from top_down_planning.cli.user import handle_status_command
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProviderRunError, mark_run_failed
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from tests.helpers import run_digests_for_config


def _create_planning_run(store: FileRunStore, run_id: str = "run-failed") -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver the feature.", "input_refs": []},
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
        phase=WHOLE_PLAN_REVIEW,
    )


def test_mark_run_failed_persists_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)

    mark_run_failed(store, "run-failed", message="provider crashed")

    run = store.load_run("run-failed")
    assert run["status"] == "failed"
    events = store.load_events("run-failed")
    assert any(event.get("type") == "run_failed" for event in events)


def test_cli_status_reports_persisted_run_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store, run_id="run-status")

    with patch("top_down_planning.cli.user.emit_payload") as emit_payload:
        with pytest.raises(SystemExit) as exit_info:
            handle_status_command(
                Namespace(run="run-status", runs_dir=str(store.root), stream_json=True)
            )
        assert exit_info.value.code == 0
        payload = emit_payload.call_args.args[0]

    assert payload["ok"] is True
    assert payload["run"]["id"] == "run-status"
    assert payload["run"]["phase"] == WHOLE_PLAN_REVIEW
    assert payload["run"]["status"] == "running"
    assert "config" in payload["run"]["digests"]


def test_provider_run_error_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run = store.load_run("run-failed")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_planner_session_id": "stub-planner-session"}
    store.save_run("run-failed", run, expected_revision)

    with patch(
        "top_down_planning.cli.user.WholePlanReviewOrchestrator.run",
        side_effect=ProviderRunError("provider crashed"),
    ):
        with pytest.raises(SystemExit) as exit_info:
            handle_resume_command(
                Namespace(run="run-failed", runs_dir=str(store.root), stream_json=False)
            )
        assert exit_info.value.code == 1

    run = store.load_run("run-failed")
    assert run["status"] == "failed"
