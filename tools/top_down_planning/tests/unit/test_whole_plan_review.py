"""Tests for mandatory whole-plan review orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProviderRunError, WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest
from core_tools.provider import StubProvider
from tests.helpers import apply_plan, create_run_kwargs, done_events, grant_capability, respond_review, script_reviewer_allocate


def _create_run_at_whole_plan_review(
    store: FileRunStore,
    run_id: str = "run-20260101T000301-000301",
    *,
    limits: dict | None = None,
    provider: StubProvider | None = None,
) -> str | None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    api = PlanItem(
        id="item-api",
        parent_id="item-root",
        order_key="0000000000",
        title="API",
        outcome="API exists.",
        acceptance=["API behavior is verifiable."],
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-api": api},
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
            "whole_plan_review": {
                "max_revision_cycles": 5,
            }
        },
        "provider": {"name": "stub"},
    }
    if limits:
        config["limits"]["whole_plan_review"].update(limits)

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_PLAN_REVIEW,
    )
    session_id = None
    if provider is not None:
        provider.script_turn(done_events(text="turn complete"))
        session_id = provider.start_primary_session(
            "planner",
            {"run_id": run_id, "phase": WHOLE_PLAN_REVIEW},
        )
        list(provider.stream_events(session_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    sessions: dict[str, str] = {}
    if session_id is not None:
        sessions["primary_planner_session_id"] = session_id
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    return session_id


def _review_respond_request(
    *,
    decision: str,
    target_revision: int = 0,
    findings: list[dict] | None = None,
) -> dict:
    return {
        "loop_id": "review-whole-plan-01",
        "target_revision": target_revision,
        "decision": decision,
        "findings": findings or [],
    }


def test_whole_plan_review_changes_then_approve_reaches_plan_validated(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)

    run_id = "run-20260101T000301-000301"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-api"],
                        "issue": "API outcome is too vague.",
                        "required_change": "Add concrete acceptance criteria.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {
                        "outcome": "REST API endpoints exist.",
                        "acceptance": [
                            "GET /health returns 200.",
                            "POST /items creates a record.",
                        ],
                    },
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="approved",
                target_revision=1,
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    assert result.outcome is None
    assert result.loop_id == "review-whole-plan-01"
    assert result.revision_cycles == 1

    review = store.load_review("run-20260101T000301-000301", "review-whole-plan-01")
    assert review["status"] == "approved"
    assert review["target_revision"] == 1

    run = store.load_run("run-20260101T000301-000301")
    assert run["phase"] == PLAN_VALIDATED
    assert run["status"] == "running"


def test_blocking_finding_prevents_approval_via_review_respond(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    store.save_review(
        "run-20260101T000301-000301",
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
        },
    )

    service = ReviewAgentService(store, "run-20260101T000301-000301")
    token = grant_capability(
        store,
        "run-20260101T000301-000301",
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    with pytest.raises(RequestError, match="blocking findings"):
        service.respond(
            _review_respond_request(
                decision="approved",
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-api"],
                        "issue": "Still vague.",
                        "required_change": "Clarify.",
                        "status": "unresolved",
                    }
                ],
            ),
            capability_token=token,
        )


def test_approval_at_stale_revision_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    store.save_review(
        "run-20260101T000301-000301",
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
        },
    )

    service = ReviewAgentService(store, "run-20260101T000301-000301")
    token = grant_capability(
        store,
        "run-20260101T000301-000301",
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    plan = store.load_plan_model("run-20260101T000301-000301")
    plan.revision = 1
    store.save_plan_model("run-20260101T000301-000301", plan, 0)

    with pytest.raises(RequestError, match="does not match current plan revision"):
        service.respond(
            _review_respond_request(decision="approved", target_revision=0),
            capability_token=token,
        )


def test_revision_cycle_limit_does_not_accept_plan(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, limits={"max_revision_cycles": 1}, provider=provider)

    run_id = "run-20260101T000301-000301"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-api"],
                        "issue": "Needs work.",
                        "required_change": "Improve acceptance.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )
    provider.script_turn(done_events(text="turn complete"))
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="changes_requested",
                target_revision=0,
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-api"],
                        "issue": "Still needs work.",
                        "required_change": "Improve acceptance.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "rejected"
    assert result.reason is not None
    assert "max_revision_cycles" in result.reason

    run = store.load_run("run-20260101T000301-000301")
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert run["status"] == "completed"
    assert run["outcome"] == "rejected"


def test_unapproved_plan_cannot_leave_whole_plan_review_phase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)

    run = store.load_run("run-20260101T000301-000301")
    assert run["phase"] == WHOLE_PLAN_REVIEW

    provider = StubProvider()
    run_id = "run-20260101T000301-000301"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="blocked",
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-root"],
                        "issue": "Plan is not viable.",
                        "required_change": "Rework the plan.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "blocked"
    run = store.load_run("run-20260101T000301-000301")
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert run["status"] == "completed"


def test_resume_after_planner_revision_skips_duplicate_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)

    provider.script_turn(done_events(text="turn complete"))
    reviewer_session_id = provider.start_reviewer_session(
        {"loop_id": "review-whole-plan-01", "phase": WHOLE_PLAN_REVIEW},
    )
    list(provider.stream_events(reviewer_session_id))

    store.save_review(
        "run-20260101T000301-000301",
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": reviewer_session_id,
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "changes_requested",
            "revision_cycles": 1,
            "findings": [
                {
                    "id": "finding-01",
                    "importance": "blocking",
                    "target_refs": ["item-api"],
                    "issue": "Needs work.",
                    "required_change": "Improve acceptance.",
                    "status": "unresolved",
                }
            ],
        },
    )

    plan = store.load_plan_model("run-20260101T000301-000301")
    plan.revision = 1
    store.save_plan_model("run-20260101T000301-000301", plan, 0)
    run = store.load_run("run-20260101T000301-000301")
    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    run["digests"]["plan"] = compute_plan_digest(plan)
    store.save_run("run-20260101T000301-000301", run, expected_revision)

    run_id = "run-20260101T000301-000301"
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="approved",
                target_revision=1,
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    assert result.revision_cycles == 1


def test_non_reviewer_respond_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    service = ReviewAgentService(store, "run-20260101T000301-000301")
    token = grant_capability(store, "run-20260101T000301-000301", role="planner", phase=WHOLE_PLAN_REVIEW)

    with pytest.raises(CapabilityDeniedError):
        service.respond(
            _review_respond_request(decision="approved"),
            capability_token=token,
        )


def test_whole_plan_package_includes_default_rubric(tmp_path: Path) -> None:
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import create_run_kwargs, minimal_resolved_config

    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    plan = store.load_plan_model("run-20260101T000301-000301")
    config = minimal_resolved_config()
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
    )
    package = build_whole_plan_review_package(
        "run-20260101T000301-000301",
        store.load_run("run-20260101T000301-000301"),
        config,
        plan,
        loop,
    )
    assert package["rubric"] == DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]
    assert package["plan_revision"] == 0
    assert "plan" in package


def test_whole_plan_package_preserves_custom_rubric(tmp_path: Path) -> None:
    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import minimal_resolved_config

    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    plan = store.load_plan_model("run-20260101T000301-000301")
    config = minimal_resolved_config()
    config["review"] = {
        "focused_plan": {"enabled": True},
        "focused_output": {"enabled": True},
        "whole_plan": {"rubric": ["coverage", "custom-quality"]},
    }
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
    )
    package = build_whole_plan_review_package(
        "run-20260101T000301-000301",
        store.load_run("run-20260101T000301-000301"),
        config,
        plan,
        loop,
    )
    assert package["rubric"] == ["coverage", "custom-quality"]


def test_review_whole_plan_rubric_config_path_is_allowed(tmp_path: Path) -> None:
    from top_down_planning.config import resolve_config
    from tests.helpers import write_config

    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = resolve_config(
        write_config(
            tmp_path / "cfg.yaml",
            """
run:
  output_goal: Goal.
review:
  whole_plan:
    rubric:
      - coverage
      - custom
""",
        ),
        cwd=workspace,
    )
    assert config["review"]["whole_plan"]["rubric"] == ["coverage", "custom"]
