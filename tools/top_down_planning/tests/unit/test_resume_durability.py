"""Resume precondition and interrupt/resume durability tests (todo 14)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.cli.user import handle_resume_command
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import (
    PlanningPhaseOrchestrator,
    ProductionPhaseOrchestrator,
    WholePlanReviewOrchestrator,
)
from top_down_planning.orchestrator.phases import (
    PLAN_VALIDATED,
    PLANNING,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.planning import build_planner_context_manifest
from top_down_planning.orchestrator.production import build_producer_context_manifest
from top_down_planning.config import (
    compute_input_digest,
    compute_output_goal_digest,
)
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.conftest import run_cli
from tests.helpers import (
    apply_plan,
    apply_production,
    create_run_kwargs,
    done_events,
    ensure_input_ref_files,
    grant_capability,
    minimal_resolved_config,
    respond_review,
    script_mandatory_clear_approval,
    script_reviewer_allocate,
    whole_plan_approval_record,
)


def _bind_config_workspace(config: dict, workspace: Path) -> dict:
    bound = dict(config)
    project = dict(bound.get("project") or {})
    project["workspace"] = str(workspace.resolve())
    bound["project"] = project
    return bound


def _run_digests(config: dict, workspace: Path) -> tuple[str, str]:
    merged = minimal_resolved_config()
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    bound = _bind_config_workspace(merged, workspace)
    ensure_input_ref_files(workspace, bound)
    return (
        compute_input_digest(bound, base_dir=workspace),
        compute_output_goal_digest(bound, base_dir=workspace),
    )


def _create_planning_run(
    store: FileRunStore,
    provider: StubProvider,
    run_id: str = "run-20260101T001101-001101",
) -> str:
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
        run={"output_goal": "Deliver the feature.", "input_refs": ["README.md"]},
        planning={
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        limits={"planning": {"max_items_added": 20, "max_agent_turns": 40}},
        provider={"name": "stub"},
    )
    bound = _bind_config_workspace(config, store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=bound),
    )

    run = store.load_run(run_id)
    provider.script_turn(done_events(signal="continue", text="planning turn"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, bound, plan),
    )
    list(provider.stream_events(session_id))

    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_planner_session_id": session_id}
    run["planning"] = {"agent_turns": 1, "items_added": 0}
    store.save_run(run_id, run, expected_revision)
    store.save_review(
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": None,
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
        },
    )
    return session_id


def _create_production_run(
    store: FileRunStore,
    provider: StubProvider,
    run_id: str = "run-20260101T001201-001201",
) -> str:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )
    config = minimal_resolved_config(
        run={
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        limits={"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        provider={"name": "stub"},
    )
    bound = _bind_config_workspace(config, store.root)
    input_digest, output_goal_digest = _run_digests(config, store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=bound),
        phase=PRODUCTION,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    run = store.load_run(run_id)
    provider.script_turn(done_events(text="producer session start"))
    session_id = provider.start_primary_session(
        "producer",
        build_producer_context_manifest(
            run_id,
            run,
            bound,
            plan,
            production=store.load_production(run_id),
        ),
    )
    list(provider.stream_events(session_id))

    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_producer_session_id": session_id}
    store.save_run(run_id, run, expected_revision)
    return session_id


def test_interrupt_planning_resume_keeps_same_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    session_id = _create_planning_run(store, provider)

    run_id = "run-20260101T001101-001101"
    provider.script_turn(
        done_events(signal="candidate_plan_ready", text="planning turn"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "add_item",
                    "temp_id": "item-api",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"kind": "work", "title": "API", "outcome": "API exists."},
                }
            ],
        ),
    )

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.session_id == session_id
    assert result.agent_turns == 2
    assert len(store.load_plan_model("run-20260101T001101-001101").items) == 2


def test_interrupt_production_resume_keeps_same_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    session_id = _create_production_run(store, provider)
    service = ProductionAgentService(store, "run-20260101T001201-001201")
    producer_token = grant_capability(
        store,
        "run-20260101T001201-001201",
        role="producer",
        phase=PRODUCTION,
    )

    service.apply(
        {
            "production_revision": 0,
            "plan_items": ["item-first"],
            "dispositions": {"item-first": {"disposition": "completed"}},
            "outputs": [],
            "contributions": [],
            "summary": "batch complete",
        },
        capability_token=producer_token,
    )

    run = store.load_run("run-20260101T001201-001201")
    assert run["sessions"]["primary_producer_session_id"] == session_id

    run_id = "run-20260101T001201-001201"
    provider.script_turn(
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=lambda: (
            apply_production(
                store,
                run_id,
                {
                    "production_revision": 1,
                    "plan_items": ["item-second"],
                    "dispositions": {"item-second": {"disposition": "completed"}},
                    "outputs": [],
                    "contributions": [],
                    "summary": "batch complete",
                },
                handler="apply",
            )(),
            apply_production(
                store,
                run_id,
                {"goal_assessment": "Output goal is fully met.", "goal_met": True},
                handler="submit_completion",
            )(),
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_OUTPUT_REVIEW
    assert result.session_id == session_id
    assert result.batch_count == 2


def test_interrupt_whole_plan_review_resume_keeps_loop_and_reviewer_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    planner_session_id = _create_planning_run(store, provider)

    run = store.load_run("run-20260101T001101-001101")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run("run-20260101T001101-001101", run, expected_revision)

    run_id = "run-20260101T001101-001101"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-plan-01",
        phase=WHOLE_PLAN_REVIEW,
        target_revision=0,
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    assert result.loop_id == "review-whole-plan-01"
    assert result.reviewer_session_id is not None

    review = store.load_review("run-20260101T001101-001101", "review-whole-plan-01")
    assert review["reviewer_session_id"] == result.reviewer_session_id

    run = store.load_run("run-20260101T001101-001101")
    assert run["sessions"]["primary_planner_session_id"] == planner_session_id


def test_resume_twice_does_not_corrupt_revision_counters(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    run = store.load_run("run-20260101T001101-001101")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run("run-20260101T001101-001101", run, expected_revision)

    revision_before = int(store.load_run("run-20260101T001101-001101")["revision"])
    first = PlanningPhaseOrchestrator(store, "run-20260101T001101-001101", provider).run()
    second = PlanningPhaseOrchestrator(store, "run-20260101T001101-001101", provider).run()

    assert first.ok is True
    assert second.ok is True
    assert first.phase == WHOLE_PLAN_REVIEW
    assert second.phase == WHOLE_PLAN_REVIEW
    assert int(store.load_run("run-20260101T001101-001101")["revision"]) == revision_before


def test_resume_cli_stream_json_for_completed_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001301-001301"
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    config = minimal_resolved_config(
        run={"output_goal": "Deliver.", "input_refs": []},
        provider={"name": "stub"},
    )
    bound = _bind_config_workspace(config, store.root)
    input_digest, output_goal_digest = _run_digests(config, store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=bound),
        phase="output_validated",
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "completed"
    run["outcome"] = "accepted"
    store.save_run(run_id, run, expected_revision)

    result = run_cli(["resume", "--run", run_id, "--runs-dir", str(tmp_path), "--stream-json"])
    payload = result.json()

    assert result.exit_code == 0
    assert payload["ok"] is True
    assert payload["phase"] == "output_validated"
    assert payload["message"] == "run already completed with final outcome"


def test_resume_completed_rejected_whole_plan_review_does_not_restart(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001401-001401"
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    config = minimal_resolved_config(
        run={"output_goal": "Deliver.", "input_refs": []},
        provider={"name": "stub"},
    )
    bound = _bind_config_workspace(config, store.root)
    input_digest, output_goal_digest = _run_digests(config, store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=bound),
        phase=WHOLE_PLAN_REVIEW,
    )
    store.save_review(
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "status": "blocked",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "findings": [],
            "revision_cycles": 0,
        },
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "completed"
    run["outcome"] = "rejected"
    store.save_run(run_id, run, expected_revision)

    result = run_cli(["resume", "--run", run_id, "--runs-dir", str(tmp_path), "--stream-json"])
    payload = result.json()

    assert result.exit_code == 0
    assert payload["ok"] is True
    assert payload["phase"] == WHOLE_PLAN_REVIEW
    assert payload["outcome"] == "rejected"
    assert "already terminated" in payload["message"]

    reviews = store.list_reviews(run_id)
    assert len(reviews) == 1
    assert reviews[0]["status"] == "blocked"
