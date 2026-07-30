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
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.conftest import run_cli
from tests.helpers import done_events, plan_apply_turn, whole_plan_approval_record


def _create_planning_run(
    store: FileRunStore,
    provider: StubProvider,
    run_id: str = "run-resume-planning",
) -> str:
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
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {
            "planning": {
                "max_expansion_iterations": 20,
                "max_agent_turns": 40,
            }
        },
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=compute_input_digest(config, base_dir=store.root),
        output_goal_digest=compute_output_goal_digest(config),
        workspace=str(store.root),
    )

    run = store.load_run(run_id)
    provider.script_turn(done_events(signal="continue", text="planning turn"))
    session_id = provider.start_primary_session(
        "planner",
        build_planner_context_manifest(run_id, run, config),
    )
    list(provider.stream_events(session_id))

    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_planner_session_id": session_id}
    run["planning"] = {"agent_turns": 1, "expansion_iterations": 0}
    store.save_run(run_id, run, expected_revision)
    return session_id


def _create_production_run(
    store: FileRunStore,
    provider: StubProvider,
    run_id: str = "run-resume-production",
) -> str:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        depends_on=["item-first"],
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
    config = {
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {
            "production": {
                "max_batches": 50,
                "max_agent_turns_per_batch": 10,
            }
        },
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=compute_input_digest(config, base_dir=store.root),
        output_goal_digest=compute_output_goal_digest(config),
        phase=PRODUCTION,
        workspace=str(store.root),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    run = store.load_run(run_id)
    provider.script_turn(done_events(text="producer session start"))
    session_id = provider.start_primary_session(
        "producer",
        build_producer_context_manifest(
            run_id,
            run,
            config,
            plan_revision=0,
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

    config = store.load_resolved_config("run-resume-planning")
    config["planning"]["max_depth"] = 9
    config_path = tmp_path / "run-resume-planning" / "resolved-config.yaml"
    from core_tools.persistence import dump_yaml

    config_path.write_text(dump_yaml(config) + "\n", encoding="utf-8")

    with pytest.raises(ResumeError, match="config digest mismatch"):
        validate_resume_preconditions(store, "run-resume-planning")


def test_resume_rejects_plan_digest_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    plan = store.load_plan_model("run-resume-planning")
    plan.items["item-root"].title = "Changed Root"
    plan.revision = 1
    store.save_plan_model("run-resume-planning", plan, 0)
    # run.json still carries the pre-change plan digest.

    with pytest.raises(ResumeError, match="plan digest mismatch"):
        validate_resume_preconditions(store, "run-resume-planning")


def test_resume_planning_missing_session_ref_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    run = store.load_run("run-resume-planning")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {}
    store.save_run("run-resume-planning", run, expected_revision)

    with pytest.raises(ResumeError, match="primary planner session reference is missing"):
        validate_resume_preconditions(store, "run-resume-planning")


def test_resume_production_missing_session_ref_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_production_run(store, provider)

    run = store.load_run("run-resume-production")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {}
    store.save_run("run-resume-production", run, expected_revision)

    with pytest.raises(ResumeError, match="primary producer session reference is missing"):
        validate_resume_preconditions(store, "run-resume-production")


def test_interrupt_planning_resume_keeps_same_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    session_id = _create_planning_run(store, provider)

    provider.script_turn(
        plan_apply_turn(
            operations=[
                {
                    "op": "add_item",
                    "temp_id": "item-api",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {"title": "API", "outcome": "API exists."},
                }
            ],
        )
    )

    result = PlanningPhaseOrchestrator(store, "run-resume-planning", provider).run()

    assert result.ok is True
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.session_id == session_id
    assert result.agent_turns == 2
    assert len(store.load_plan_model("run-resume-planning").items) == 2


def test_interrupt_production_resume_keeps_same_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    session_id = _create_production_run(store, provider)
    service = ProductionAgentService(store, "run-resume-production")

    service.apply(
        {
            "production_revision": 0,
            "plan_items": ["item-first"],
            "dispositions": {"item-first": {"disposition": "completed"}},
            "outputs": [],
            "contributions": [],
            "summary": "batch complete",
        },
        role="producer",
    )

    run = store.load_run("run-resume-production")
    assert run["sessions"]["primary_producer_session_id"] == session_id
    validate_resume_preconditions(store, "run-resume-production")

    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "production_apply",
                "role": "producer",
                "request": {
                    "production_revision": 1,
                    "plan_items": ["item-second"],
                    "dispositions": {"item-second": {"disposition": "completed"}},
                    "outputs": [],
                    "contributions": [],
                    "summary": "batch complete",
                },
            },
            {
                "type": "tool_call",
                "tool": "production_submit_completion",
                "role": "producer",
                "request": {"goal_assessment": "Output goal is fully met."},
            },
            *done_events(signal="batch_complete", text="production turn"),
        ]
    )

    result = ProductionPhaseOrchestrator(store, "run-resume-production", provider).run()

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

    run = store.load_run("run-resume-planning")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run("run-resume-planning", run, expected_revision)

    provider.script_turn(
        [
            {
                "type": "tool_call",
                "tool": "review_respond",
                "role": "reviewer",
                "request": {
                    "loop_id": "review-whole-plan-01",
                    "target_revision": 0,
                    "decision": "approved",
                    "findings": [],
                },
            },
            *done_events(text="turn complete"),
        ]
    )

    result = WholePlanReviewOrchestrator(store, "run-resume-planning", provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    assert result.loop_id == "review-whole-plan-01"
    assert result.reviewer_session_id is not None

    review = store.load_review("run-resume-planning", "review-whole-plan-01")
    assert review["reviewer_session_id"] == result.reviewer_session_id

    run = store.load_run("run-resume-planning")
    assert run["sessions"]["primary_planner_session_id"] == planner_session_id


def test_resume_twice_does_not_corrupt_revision_counters(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    run = store.load_run("run-resume-planning")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run("run-resume-planning", run, expected_revision)

    revision_before = int(store.load_run("run-resume-planning")["revision"])
    first = PlanningPhaseOrchestrator(store, "run-resume-planning", provider).run()
    second = PlanningPhaseOrchestrator(store, "run-resume-planning", provider).run()

    assert first.ok is True
    assert second.ok is True
    assert first.phase == WHOLE_PLAN_REVIEW
    assert second.phase == WHOLE_PLAN_REVIEW
    assert int(store.load_run("run-resume-planning")["revision"]) == revision_before


def test_resume_cli_rejects_missing_session_ref(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_planning_run(store, provider)

    run = store.load_run("run-resume-planning")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {}
    store.save_run("run-resume-planning", run, expected_revision)

    with pytest.raises(SystemExit) as exc:
        handle_resume_command(
            Namespace(
                run="run-resume-planning",
                runs_dir=str(tmp_path),
                stream_json=True,
            )
        )

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "primary planner session reference is missing" in captured.out


def test_resume_cli_stream_json_for_completed_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-complete"
    root = PlanItem("item-root", None, "0000000000", "Root")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": []},
        "planning": {"stop_hint": "Stop.", "max_depth": 4, "max_expansion_per_item": 7},
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=compute_input_digest(config, base_dir=store.root),
        output_goal_digest=compute_output_goal_digest(config),
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


def test_resume_production_without_plan_approval_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_production_run(store, provider)

    review_path = store.reviews_dir("run-resume-production") / "review-whole-plan-01.json"
    review_path.unlink()

    with pytest.raises(ResumeError, match="lacks whole-plan approval"):
        validate_resume_preconditions(store, "run-resume-production")


def test_resume_plan_validated_allows_missing_producer_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-plan-validated"
    root = PlanItem("item-root", None, "0000000000", "Root")
    first = PlanItem("item-first", "item-root", "0000000000", "First")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": []},
        "planning": {"stop_hint": "Stop.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=compute_input_digest(config, base_dir=store.root),
        output_goal_digest=compute_output_goal_digest(config),
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
    service = ProductionAgentService(store, "run-resume-production")
    service.request_amendment(
        {
            "evidence": "Missing branch.",
            "affected_refs": ["item-root"],
            "summary": "Need more plan detail.",
        },
        role="producer",
    )

    run = store.load_run("run-resume-production")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = {"primary_producer_session_id": run["sessions"]["primary_producer_session_id"]}
    store.save_run("run-resume-production", run, expected_revision)

    with pytest.raises(ResumeError, match="primary planner session reference is missing"):
        validate_resume_preconditions(store, "run-resume-production")


def test_resume_plan_amendment_without_pending_request_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-amendment-phase"
    root = PlanItem("item-root", None, "0000000000", "Root")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": []},
        "planning": {"stop_hint": "Stop.", "max_depth": 4, "max_expansion_per_item": 7},
        "provider": {"name": "stub"},
    }
    store.create_run(
        run_id,
        plan=plan,
        resolved_config=config,
        input_digest=compute_input_digest(config, base_dir=store.root),
        output_goal_digest=compute_output_goal_digest(config),
        phase="plan_amendment",
    )

    with pytest.raises(ResumeError, match="without a pending amendment request"):
        validate_resume_preconditions(store, run_id)
