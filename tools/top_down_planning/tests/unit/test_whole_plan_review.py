"""Tests for mandatory whole-plan review orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.persistence.session_bindings import update_primary_binding

from top_down_planning.agent_tool import ReviewAgentService, RevisionConflictError
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProviderRunError, WholePlanReviewOrchestrator
from top_down_planning.orchestrator.mandatory_whole_review import ReviewLoopDriver
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    make_review_loop,
    plan_root_item,
    ensure_plan_work_scope_contracts,
    save_review_payload,
    create_run_kwargs,
    done_events,
    grant_capability,
    mandatory_scope_review_respond_request,
    mandatory_initial_respond_request,
    mandatory_plan_digest,
    mandatory_verification_needs_revision_request,
    mandatory_verification_respond_request,
    respond_review,
    script_mandatory_clear_approval,
    script_verification_then_scope_review_approval,
    prepare_loop_for_scope_review_respond,
)


def _create_run_at_whole_plan_review(
    store: FileRunStore,
    run_id: str = "run-20260101T000301-000301",
    *,
    limits: dict | None = None,
    provider: StubProvider | None = None,
) -> str | None:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
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
    plan = ensure_plan_work_scope_contracts(
        Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-api": api},
        )
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
    }
    if limits:
        for key, value in limits.items():
            existing = config["limits"].get(key)
            if isinstance(value, dict) and isinstance(existing, dict):
                existing.update(value)
            else:
                config["limits"][key] = value

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
    sessions = dict(run["sessions"])
    if session_id is not None:
        sessions = update_primary_binding(sessions, role="planner", provider_session_id=session_id)
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop

    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=0,
        config=config,
    )
    save_review_payload(store, run_id, loop.to_dict())
    return session_id


def _review_respond_request(
    *,
    decision: str,
    target_revision: int = 0,
    findings: list[dict] | None = None,
    store: FileRunStore | None = None,
    run_id: str | None = None,
) -> dict:
    assert store is not None and run_id is not None
    return mandatory_initial_respond_request(
        store,
        run_id,
        loop_id="review-whole-plan-01",
        target_revision=target_revision,
        review_type="whole_plan",
        decision=decision,
        findings=findings,
    )


def test_whole_plan_review_changes_then_approve_reaches_plan_validated(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)

    run_id = "run-20260101T000301-000301"
    respond_review(
        store,
        run_id,
        _review_respond_request(
            decision="changes_requested",
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-api"],
                    "issue": "API outcome is too vague.",
                    "recommended_change": "Add concrete acceptance criteria.",
                    "status": "unresolved",
                }
            ],
            store=store,
            run_id=run_id,
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    apply_plan(
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
    )()
    script_verification_then_scope_review_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-plan-01",
        phase=WHOLE_PLAN_REVIEW,
        target_revision=1,
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    assert result.outcome is None
    assert result.loop_id == "review-whole-plan-01"
    review = store.load_review(run_id, "review-whole-plan-01")
    assert review.get("verification_result")
    assert review.get("scope_review_result")

    review = store.load_review("run-20260101T000301-000301", "review-whole-plan-01")
    assert review["status"] == "approved"
    assert review["target_revision"] == 1
    assert review.get("active_stage") == "scope_review"
    assert review.get("scope_review_rounds", 0) >= 1

    run = store.load_run("run-20260101T000301-000301")
    assert run["phase"] == PLAN_VALIDATED
    assert run["status"] == "running"


def test_blocking_finding_prevents_approval_via_review_respond(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    save_review_payload(store, "run-20260101T000301-000301", {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "finding_set_id": "review-whole-plan-01-fs-01",
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
    response = service.respond(
        _review_respond_request(
            decision="approved",
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-api"],
                    "issue": "Still vague.",
                    "recommended_change": "Clarify.",
                    "status": "unresolved",
                }
            ],
            store=store,
            run_id="run-20260101T000301-000301",
        ),
        capability_token=token,
    )
    assert response["derived_outcome"] == "changes_requested"
    assert response["status"] == "changes_requested"


def test_approval_at_stale_revision_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    save_review_payload(store, "run-20260101T000301-000301", {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "finding_set_id": "review-whole-plan-01-fs-01",
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

    with pytest.raises(RevisionConflictError) as excinfo:
        service.respond(
            _review_respond_request(
                decision="approved",
                target_revision=0,
                store=store,
                run_id="run-20260101T000301-000301",
            ),
            capability_token=token,
        )
    assert excinfo.value.code == "revision_conflict"
    assert excinfo.value.expected == 0
    assert excinfo.value.actual == 1


from tests.unit.test_mandatory_whole_review_driver import _FakeAdapter, _create_driver_run


def test_revision_cycle_limit_does_not_accept_plan(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000301-000301"
    planner_session_id, loop_id = _create_driver_run(
        store,
        run_id,
        provider=provider,
        limits={"max_revision_cycles": 1},
    )
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-root"],
                        "issue": "Needs work.",
                        "recommended_change": "Improve acceptance.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
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
                    "item_id": "item-root",
                    "patch": {"outcome": "Improved outcome."},
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )

    def _needs_revision_respond() -> None:
        loop = store.load_review(run_id, loop_id)
        finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
        respond_review(
            store,
            run_id,
            mandatory_verification_needs_revision_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "unresolved",
                        "evidence": ["still insufficient"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=_needs_revision_respond,
    )

    result = ReviewLoopDriver(store, run_id, provider, adapter).run()

    assert result.ok is False
    assert result.outcome is None
    assert result.reason is not None
    assert "max_revision_cycles" in result.reason

    run = store.load_run(run_id)
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert run["status"] == "paused"
    assert run["outcome"] is None
    assert run["stop"]["code"] == "limit_exhausted"


def test_unapproved_plan_cannot_leave_whole_plan_review_phase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)

    run = store.load_run("run-20260101T000301-000301")
    assert run["phase"] == WHOLE_PLAN_REVIEW

    provider = StubProvider()
    run_id = "run-20260101T000301-000301"
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
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-root"],
                        "issue": "Plan is not viable.",
                        "recommended_change": "Rework the plan.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
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

    save_review_payload(store, "run-20260101T000301-000301", {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": reviewer_session_id,
            "target_revision": 1,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "revision_cycles": 1,
            "lifecycle_status": "verification_pending",
            "active_stage": "finding_verification",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-api"],
                    "issue": "Needs work.",
                    "recommended_change": "Improve acceptance.",
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
    respond_review(
        store,
        run_id,
        mandatory_verification_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=1,
            review_type="whole_plan",
            finding_set_id="review-whole-plan-01-fs-01",
            finding_results=[
                {
                    "finding_id": "finding-01",
                    "disposition": "resolved",
                    "evidence": ["improved"],
                    "direct_side_effects": [],
                }
            ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=1,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=1,
            review_type="whole_plan",
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()

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
            _review_respond_request(
                decision="approved",
                store=store,
                run_id="run-20260101T000301-000301",
            ),
            capability_token=token,
        )


def test_default_whole_plan_rubric_covers_advisory_themes() -> None:
    from top_down_planning.config.defaults import DEFAULT_CONFIG

    rubric = DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]
    joined = "\n".join(rubric).casefold()
    for theme in (
        "internal consistency",
        "hierarchy",
        "dependencies",
        "granularity",
        "contract ownership",
        "plan cleanliness",
        "coverage",
        "traceability",
    ):
        assert theme in joined, f"missing advisory theme {theme!r} in {rubric}"


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
    loop = make_review_loop(
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
    assert [
        item["text"] for item in package["rubric_items"]
    ] == DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]
    assert package["target_revision"] == 0
    assert "target_digest" in package
    assert "plan_revision" not in package
    assert "plan" in package
    assert package["plan"]["view"] == "active"
    assert "analysis_context" in package
    assert "preflight_candidates" in package["analysis_context"]
    assert package["review_budgets"] == {
        "revision_cycles": 0,
        "scope_review_rounds": 0,
        "gate_agent_turns": 0,
        "max_agent_turns_per_gate": 5,
    }


def test_whole_plan_package_declares_contract_v2_and_analysis_context(
    tmp_path: Path,
) -> None:
    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import minimal_resolved_config

    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    plan = store.load_plan_model("run-20260101T000301-000301")
    config = minimal_resolved_config()
    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=0,
        config=config,
    )
    package = build_whole_plan_review_package(
        "run-20260101T000301-000301",
        store.load_run("run-20260101T000301-000301"),
        config,
        plan,
        loop,
    )
    assert package["review_record_schema_version"] == 2
    assert package["review_contract_version"] == 2
    assert "analysis_context" in package
    assert "preflight_candidates" in package["analysis_context"]
    assert package["analysis_context"]["preflight_candidates"] is not None


def test_whole_plan_scope_review_package_includes_rubric_omits_active_families(
    tmp_path: Path,
) -> None:
    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from top_down_planning.domain.finding_families import FindingFamily, compute_family_fingerprint
    from top_down_planning.domain.reviews import ReviewFinding
    from tests.helpers import minimal_resolved_config

    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    plan = store.load_plan_model("run-20260101T000301-000301")
    config = minimal_resolved_config()
    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=0,
        config=config,
    )
    loop = loop.__class__.from_dict(
        {
            **loop.to_dict(),
            "lifecycle_status": "scope_review_pending",
            "active_stage": "scope_review",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "finding_families": [
                FindingFamily(
                    id="family-closed",
                    finding_set_id="review-whole-plan-01-fs-01",
                    rule_id="coverage.traceability_gap",
                    subject_key="prior",
                    scope_kind="active-plan",
                    family_fingerprint=compute_family_fingerprint(
                        rule_id="coverage.traceability_gap",
                        subject_key="prior",
                        scope_kind="active-plan",
                    ),
                    title="Prior family title",
                    seed_finding_id="f-1",
                    confirmed_finding_ids=["f-1"],
                    candidate_refs=[],
                    recommended_change="Do not surface this in scope review",
                ).to_dict()
            ],
            "findings": [
                ReviewFinding(
                    id="f-1",
                    severity="blocker",
                    category="correctness",
                    target_refs=["item-api"],
                    issue="prior",
                    recommended_change="prior",
                    family_id="family-closed",
                    status="resolved",
                ).to_dict()
            ],
        }
    )
    package = build_whole_plan_review_package(
        "run-20260101T000301-000301",
        store.load_run("run-20260101T000301-000301"),
        config,
        plan,
        loop,
    )
    assert package["rubric_items"]
    assert "active_families" not in package
    assert "Prior family title" not in str(package)
    assert package["analysis_context"]["preflight_candidates"] is not None


def test_whole_plan_package_includes_overlap_warnings(tmp_path: Path) -> None:
    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import minimal_resolved_config, plan_root_item

    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    plan = Plan(
        id="plan-overlap-package",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": plan_root_item(
                title="Deliver the feature",
                outcome="Root outcome.",
            ),
            "item-parent": PlanItem(
                id="item-parent",
                parent_id="item-root",
                order_key="0000000000",
                title="Parent work",
                outcome="Parent outcome.",
                acceptance=["parent ok"],
                kind="work",
            ),
            "item-child": PlanItem(
                id="item-child",
                parent_id="item-parent",
                order_key="0000000000",
                title="Child work",
                outcome="Child outcome.",
                acceptance=["child ok"],
                kind="work",
            ),
        },
    )
    config = minimal_resolved_config()
    loop = make_review_loop(
        id="review-whole-plan-02",
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
    assert any(
        issue.get("code") == "executable_parent_overlap"
        for issue in package["analysis_context"]["preflight_candidates"]
    )


def test_whole_plan_package_includes_empty_aggregate_warnings(tmp_path: Path) -> None:
    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import minimal_resolved_config

    store = FileRunStore(tmp_path)
    _create_run_at_whole_plan_review(store)
    plan = Plan(
        id="plan-empty-aggregate",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
        },
    )
    config = minimal_resolved_config()
    loop = make_review_loop(
        id="review-whole-plan-03",
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
    assert any(
        issue.get("code") == "aggregate_without_descendants"
        for issue in package["analysis_context"]["preflight_candidates"]
    )


def test_whole_plan_package_includes_dependency_cycle_issues(tmp_path: Path) -> None:
    from top_down_planning.domain.reviews import ReviewLoop
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import minimal_resolved_config, plan_root_item

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000302-000302"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    plan = Plan(
        id="plan-cycle-package",
        revision=0,
        output_goal="Deliver the feature.",
        items={
            "item-root": plan_root_item(
                title="Deliver the feature",
                outcome="Root outcome.",
            ),
            "item-a": PlanItem(
                id="item-a",
                parent_id="item-root",
                order_key="0000000000",
                title="A",
                outcome="A.",
                kind="work",
                depends_on=["item-b"],
            ),
            "item-b": PlanItem(
                id="item-b",
                parent_id="item-root",
                order_key="0000000001",
                title="B",
                outcome="B.",
                kind="work",
                depends_on=["item-a"],
            ),
        },
    )
    config = minimal_resolved_config()
    loop = make_review_loop(
        id="review-whole-plan-04",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
    )
    package = build_whole_plan_review_package(
        run_id,
        store.load_run(run_id),
        config,
        plan,
        loop,
    )
    assert any(
        issue.get("code") == "dependency_cycle"
        for issue in package["analysis_context"]["preflight_candidates"]
    )


def test_whole_plan_restart_after_approval_persisted_completes_phase_once(
    tmp_path: Path,
) -> None:
    """ORCH-010: approved loop without phase advance must not spawn a second mandatory loop."""

    from tests.helpers import whole_plan_approval_record

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000301-000301"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    revision_before = int(store.load_run(run_id)["revision"])
    provider = StubProvider()

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is True
    assert store.load_run(run_id)["phase"] == PLAN_VALIDATED
    assert int(store.load_run(run_id)["revision"]) == revision_before + 1

    whole_plan_loops = [
        payload for payload in store.list_reviews(run_id) if payload.get("type") == "whole_plan"
    ]
    assert len(whole_plan_loops) == 1
    approved_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "whole_plan_review_approved"
    ]
    assert len(approved_events) == 1

    repeat = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert repeat.ok is True
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "whole_plan_review_approved"
        ]
    ) == 1


def test_whole_plan_approval_commit_crash_retries_phase_transition_once(
    tmp_path: Path,
) -> None:
    from tests.helpers import whole_plan_approval_record
    from tests.unit.test_commit_crash_recovery import _crash_after_dest_replace_count

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000302-000302"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    provider = StubProvider()

    with patch.object(Path, "replace", _crash_after_dest_replace_count(1)):
        with pytest.raises(OSError, match="simulated crash"):
            WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert store.load_run(run_id)["phase"] == WHOLE_PLAN_REVIEW
    approved_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "whole_plan_review_approved"
    ]
    assert approved_events == []

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is True
    assert store.load_run(run_id)["phase"] == PLAN_VALIDATED
    assert len(
        [
            event
            for event in store.load_events(run_id)
            if event.get("type") == "whole_plan_review_approved"
        ]
    ) == 1


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
    loop = make_review_loop(
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
    assert [item["text"] for item in package["rubric_items"]] == [
        "coverage",
        "custom-quality",
    ]


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
