"""Durable phase-entry audit events from RunEngine continuation."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import create_provider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _create_run(
    store: FileRunStore,
    run_id: str = "run-20260101T009906-009906",
    *,
    phase: str = "whole_plan_review",
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
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


def test_engine_persists_phase_entry_blocked_on_digest_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store, phase=PLANNING)
    run_id = "run-20260101T009906-009906"

    run = store.load_run(run_id)
    digests = dict(run.get("digests") or {})
    digests["context_spec"] = "0" * 64
    expected = int(run["revision"])
    run = dict(run)
    run["digests"] = digests
    run["revision"] = expected + 1
    store.save_run(run_id, run, expected)

    engine = RunEngine(
        store,
        create_provider=lambda cfg, workspace: create_provider(cfg, workspace=workspace),
    )
    result = engine.continue_run(run_id, single_step=True)

    assert result.ok is False
    events = store.load_events(run_id)
    attempted = [event for event in events if event.get("type") == "phase_entry_attempted"]
    blocked = [event for event in events if event.get("type") == "phase_entry_blocked"]
    assert len(attempted) == 1
    assert attempted[0]["phase"] == PLANNING
    assert len(blocked) == 1
    assert blocked[0]["phase"] == PLANNING
    assert blocked[0]["error_code"] == "digest_mismatch"
    assert blocked[0]["digest_kind"] == "context_spec"
    assert "expected_digest" in blocked[0]
    assert "actual_digest" in blocked[0]
    assert not any(event.get("type") == "reviewer_session_started" for event in events)
