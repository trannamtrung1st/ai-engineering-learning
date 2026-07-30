"""Tests for operational failure handling (proposal §15)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from core_tools.provider import create_provider
from top_down_planning.cli.user import handle_resume_command
from top_down_planning.cli.user import handle_status_command
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import mark_run_failed, sanitize_operational_error
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _create_run(
    store: FileRunStore,
    run_id: str = "run-failed",
    *,
    phase: str = WHOLE_PLAN_REVIEW,
) -> None:
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
    config = minimal_resolved_config(
        run={"output_goal": "Deliver the feature.", "input_refs": []},
        planning={"max_depth": 4, "max_expansion_per_item": 7},
        provider={"name": "stub"},
    )
    config["project"]["workspace"] = str(store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=phase,
    )


def test_mark_run_failed_persists_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)

    mark_run_failed(store, "run-failed", message="provider crashed")

    run = store.load_run("run-failed")
    assert run["status"] == "failed"
    events = store.load_events("run-failed")
    assert any(event.get("type") == "run_failed" for event in events)


def test_sanitize_operational_error_redacts_paths() -> None:
    message = sanitize_operational_error(
        RuntimeError("failed to write /tmp/secret/run.json")
    )
    assert "/tmp/secret/run.json" not in message
    assert "<path>" in message


def test_cli_status_reports_persisted_run_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, run_id="run-status")

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


def test_engine_provider_run_error_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda config, workspace: create_provider(config, workspace=workspace),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=ProviderRunError("provider crashed"),
    ):
        result = engine.continue_run("run-failed", single_step=True)

    assert result.ok is False
    assert store.load_run("run-failed")["status"] == "failed"
    events = store.load_events("run-failed")
    assert any(event.get("type") == "run_failed" for event in events)


def test_engine_operational_exception_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda config, workspace: create_provider(config, workspace=workspace),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=RuntimeError("orchestrator exploded"),
    ):
        result = engine.continue_run("run-failed", single_step=True)

    assert result.ok is False
    assert result.reason == "orchestrator exploded"
    assert store.load_run("run-failed")["status"] == "failed"


def test_engine_store_exception_sets_failed_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    engine = RunEngine(
        store,
        create_provider=lambda config, workspace: create_provider(config, workspace=workspace),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=PersistenceError("disk full"),
    ):
        result = engine.continue_run("run-failed", single_step=True)

    assert result.ok is False
    assert store.load_run("run-failed")["status"] == "failed"


def test_provider_run_error_resume_exits_nonzero(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    run = store.load_run("run-failed")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_planner_session_id": "stub-planner-session"}
    store.save_run("run-failed", run, expected_revision)

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=ProviderRunError("provider crashed"),
    ):
        with pytest.raises(SystemExit) as exit_info:
            handle_resume_command(
                Namespace(run="run-failed", runs_dir=str(store.root), stream_json=False)
            )
        assert exit_info.value.code == 1

    assert store.load_run("run-failed")["status"] == "failed"
