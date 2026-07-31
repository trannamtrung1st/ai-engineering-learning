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
    ResumeError,
    WholePlanReviewOrchestrator,
    validate_resume_preconditions,
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
    compute_context_digest_from_config,
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
    script_reviewer_allocate,
    whole_plan_approval_record,
)


def _bind_config_workspace(config: dict, workspace: Path) -> dict:
    bound = dict(config)
    project = dict(bound.get("project") or {})
    project["workspace"] = str(workspace.resolve())
    bound["project"] = project
    return bound


def _run_digests(config: dict, workspace: Path) -> tuple[str, str, str]:
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
        compute_context_digest_from_config(bound, workspace=workspace),
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
    input_digest, output_goal_digest, context_digest = _run_digests(config, store.root)
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


def test_resume_rejects_config_digest_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    config = store.load_resolved_config("run-20260101T001101-001101")
    config["planning"]["max_depth"] = 9
    config_path = tmp_path / "run-20260101T001101-001101" / "resolved-config.yaml"
    from core_tools.persistence import dump_yaml

    config_path.write_text(dump_yaml(config) + "\n", encoding="utf-8")

    with pytest.raises(ResumeError, match="semantic config digest mismatch"):
        validate_resume_preconditions(store, "run-20260101T001101-001101")


def test_resume_rejects_plan_digest_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    plan = store.load_plan_model("run-20260101T001101-001101")
    plan.items["item-root"].title = "Changed Root"
    plan.revision = 1
    store.save_plan_model("run-20260101T001101-001101", plan, 0)
    # run.json still carries the pre-change plan digest.

    with pytest.raises(ResumeError, match="plan digest mismatch"):
        validate_resume_preconditions(store, "run-20260101T001101-001101")


def test_resume_planning_missing_session_ref_allowed(tmp_path: Path) -> None:
    """Interrupt before planner session persist may resume and start the owner."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    run = store.load_run("run-20260101T001101-001101")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {}
    store.save_run("run-20260101T001101-001101", run, expected_revision)

    preconditions = validate_resume_preconditions(store, "run-20260101T001101-001101")
    assert preconditions.phase == PLANNING
    assert preconditions.status == "running"


def test_resume_production_missing_session_ref_allowed(tmp_path: Path) -> None:
    """Interrupt after entering production but before producer persist may resume."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_production_run(store, provider)

    run = store.load_run("run-20260101T001201-001201")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {}
    store.save_run("run-20260101T001201-001201", run, expected_revision)

    preconditions = validate_resume_preconditions(store, "run-20260101T001201-001201")
    assert preconditions.phase == PRODUCTION
    assert preconditions.status == "running"


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
    validate_resume_preconditions(store, "run-20260101T001201-001201")

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
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            {
                "loop_id": "review-whole-plan-01",
                "target_revision": 0,
                "decision": "approved",
                "findings": [],
            },
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
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
    input_digest, output_goal_digest, context_digest = _run_digests(config, store.root)
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
    input_digest, output_goal_digest, context_digest = _run_digests(config, store.root)
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

    preconditions = validate_resume_preconditions(store, run_id)
    assert preconditions.status == "completed"
    assert preconditions.outcome == "rejected"
    assert preconditions.phase == WHOLE_PLAN_REVIEW

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


def test_resume_production_without_plan_approval_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_production_run(store, provider)

    review_path = store.reviews_dir("run-20260101T001201-001201") / "review-whole-plan-01.json"
    review_path.unlink()

    with pytest.raises(ResumeError, match="lacks whole-plan approval"):
        validate_resume_preconditions(store, "run-20260101T001201-001201")


def test_resume_plan_validated_allows_missing_producer_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001501-001501"
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    first = PlanItem("item-first", "item-root", "0000000000", "First", kind="work")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first},
    )
    config = minimal_resolved_config(
        run={"output_goal": "Deliver.", "input_refs": []},
        limits={"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        provider={"name": "stub"},
    )
    bound = _bind_config_workspace(config, store.root)
    input_digest, output_goal_digest, context_digest = _run_digests(config, store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=bound),
        phase=PLAN_VALIDATED,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    preconditions = validate_resume_preconditions(store, run_id)
    assert preconditions.phase == PLAN_VALIDATED


def test_resume_production_with_pending_amendment_requires_planner_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_production_run(store, provider)
    service = ProductionAgentService(store, "run-20260101T001201-001201")
    service.request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        capability_token=grant_capability(
            store,
            "run-20260101T001201-001201",
            role="producer",
            phase=PRODUCTION,
        ),
    )

    run = store.load_run("run-20260101T001201-001201")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_producer_session_id": run["sessions"]["primary_producer_session_id"]}
    store.save_run("run-20260101T001201-001201", run, expected_revision)

    with pytest.raises(ResumeError, match="primary planner session reference is missing"):
        validate_resume_preconditions(store, "run-20260101T001201-001201")


def test_resume_plan_amendment_without_pending_request_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001601-001601"
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
    input_digest, output_goal_digest, context_digest = _run_digests(config, store.root)
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=bound),
        phase="plan_amendment",
    )

    with pytest.raises(ResumeError, match="without a pending amendment request"):
        validate_resume_preconditions(store, run_id)
