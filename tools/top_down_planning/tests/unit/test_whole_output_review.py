"""Tests for mandatory whole-output review orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import atomic_write_json
from core_tools.provider import StubProvider
from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.finding_families import FindingFamily, compute_family_fingerprint
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewFinding, ReviewLoop
from top_down_planning.orchestrator import ProviderRunError, WholeOutputReviewOrchestrator
from top_down_planning.orchestrator.mandatory_review_stages import enter_owner_revision_cycle
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.session_bindings import update_primary_binding
from tests.helpers import (
    apply_production,
    create_run_kwargs,
    done_events,
    ensure_plan_work_scope_contracts,
    grant_capability,
    make_review_loop,
    mandatory_initial_respond_request,
    mandatory_output_digest,
    mandatory_scope_review_respond_request,
    mandatory_verification_respond_request,
    plan_root_item,
    record_finding_actions,
    respond_review,
    save_review_payload,
    script_mandatory_clear_approval,
    script_verification_then_scope_review_approval,
    sessions_with_primary_session,
    StallingAfterEventsProvider,
    whole_plan_approval_record,
)


def _create_run_at_whole_output_review(
    store: FileRunStore,
    run_id: str = "run-20260101T000801-000801",
    *,
    limits: dict | None = None,
    provider: StubProvider | None = None,
    goal_assessment: str = "Output goal is fully met.",
) -> str | None:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
        kind="work",
    )
    plan = ensure_plan_work_scope_contracts(
        Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-leaf": leaf},
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
            "whole_output_review": {
                "max_revision_cycles": 5,
            }
        },
    }
    if limits:
        config["limits"]["whole_output_review"].update(limits)

    production = {
        "revision": 2,
        "output_revision": 1,
        "batches": [
            {
                "id": "batch-01",
                "plan_items": ["item-leaf"],
                "status": "completed",
                "result": {
                    "outputs": [],
                    "contributions": [],
                    "dispositions": {"item-leaf": {"disposition": "completed"}},
                    "summary": "done",
                    "empty_output": False,
                    "goal_assessment": "",
                },
            }
        ],
        "dispositions": {"item-leaf": "completed"},
        "output_evidence": [],
        "completion_claim": {
            "goal_assessment": goal_assessment,
            "goal_met": True,
            "summary": "All items complete.",
            "plan_revision": 0,
            "output_revision": 1,
            "all_applicable_items_processed": True,
        },
    }

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_OUTPUT_REVIEW,
        production=production,
    )
    save_review_payload(store, run_id,
        whole_plan_approval_record(
            store,
            run_id,
            id="review-whole-plan-01",
            reviewer_session_id="stub-session-plan-reviewer",
        ),
    )

    session_id = None
    if provider is not None:
        provider.script_turn(done_events(text="turn complete"))
        session_id = provider.start_primary_session(
            "producer",
            {"run_id": run_id, "phase": WHOLE_OUTPUT_REVIEW},
        )
        list(provider.stream_events(session_id))

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    sessions = dict(run["sessions"])
    if session_id is not None:
        sessions = update_primary_binding(sessions, role="producer", provider_session_id=session_id)
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    save_review_payload(store, run_id, {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "target_revision": int(production["output_revision"]),
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    return session_id


def _review_respond_request(
    *,
    decision: str,
    target_revision: int = 1,
    findings: list[dict] | None = None,
    store: FileRunStore | None = None,
    run_id: str | None = None,
) -> dict:
    assert store is not None and run_id is not None
    return mandatory_initial_respond_request(
        store,
        run_id,
        loop_id="review-whole-output-01",
        target_revision=target_revision,
        review_type="whole_output",
        decision=decision,
        findings=findings,
    )


def test_whole_output_review_approve_reaches_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)

    run_id = "run-20260101T000801-000801"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=1,
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    assert result.outcome == "accepted"
    assert result.loop_id == "review-whole-output-01"

    run = store.load_run("run-20260101T000801-000801")
    assert run["status"] == "completed"
    assert run["outcome"] == "accepted"


def test_whole_output_review_changes_then_approve_reaches_accepted(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    run_id = "run-20260101T000801-000801"
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
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing.",
                    "recommended_change": "Add artifact reference.",
                    "status": "unresolved",
                }
            ],
            store=store,
            run_id=run_id,
        ),
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id="review-whole-output-01",
    )()
    apply_production(
        store,
        run_id,
        {
            "production_revision": 2,
            "evidence_revision": True,
            "plan_items": ["item-leaf"],
            "dispositions": {
                "item-leaf": {
                    "disposition": "completed",
                    "evidence": "Added artifact reference.",
                }
            },
            "outputs": [
                {
                    "id": "output-leaf",
                    "type": "artifact",
                    "ref": "artifacts/leaf.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-leaf",
                    "output_refs": ["output-leaf"],
                    "summary": "Revised evidence.",
                }
            ],
            "summary": "Addressed reviewer finding.",
        },
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    apply_production(
        store,
        run_id,
        {
            "goal_assessment": "Output goal is fully met after revision.",
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    script_verification_then_scope_review_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=2,
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.outcome == "accepted"
    review = store.load_review(run_id, "review-whole-output-01")
    assert review.get("verification_result")
    assert review.get("scope_review_result")


def test_whole_output_owner_revision_closes_on_completion_claim_while_stream_stalls(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StallingAfterEventsProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    run_id = "run-20260101T000801-000801"
    loop_id = "review-whole-output-01"
    findings = [
        {
            "id": "finding-01",
            "severity": "blocker",
            "category": "correctness",
            "target_refs": ["item-leaf"],
            "issue": "Output evidence is missing.",
            "recommended_change": "Add artifact reference.",
            "status": "unresolved",
        }
    ]

    provider.script_turn(
        done_events(text="initial review complete"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_output",
                decision="changes_requested",
                findings=findings,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        ),
    )

    def _producer_revision() -> None:
        apply_production(
            store,
            run_id,
            {
                "production_revision": 2,
                "evidence_revision": True,
                "plan_items": ["item-leaf"],
                "dispositions": {
                    "item-leaf": {
                        "disposition": "completed",
                        "evidence": "Added artifact reference.",
                    }
                },
                "outputs": [
                    {
                        "id": "output-leaf",
                        "type": "artifact",
                        "ref": "artifacts/leaf.txt",
                    }
                ],
                "contributions": [
                    {
                        "item_id": "item-leaf",
                        "output_refs": ["output-leaf"],
                        "summary": "Revised evidence.",
                    }
                ],
                "summary": "Addressed reviewer finding.",
            },
            handler="apply",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        apply_production(
            store,
            run_id,
            {
                "goal_assessment": "Output goal is fully met after revision.",
            },
            handler="submit_completion",
            phase=WHOLE_OUTPUT_REVIEW,
        )()

    provider.script_turn(
        [
            {"type": "assistant", "text": "revising output evidence"},
            {"type": "assistant", "text": "still streaming without done"},
        ],
        mutate_store=_producer_revision,
    )

    def _verification_respond() -> None:
        loop = store.load_review(run_id, loop_id)
        finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
        target_revision = int(store.load_production(run_id)["output_revision"])
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_type="whole_output",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["artifact added"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="verification complete"), mutate_store=_verification_respond)

    def _scope_respond() -> None:
        target_revision = int(store.load_production(run_id)["output_revision"])
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="scope review complete"), mutate_store=_scope_respond)

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.outcome == "accepted"
    review = store.load_review(run_id, loop_id)
    assert review.get("verification_result")
    assert review.get("scope_review_result")


def test_missing_goal_assessment_blocks_acceptance(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(
        store,
        provider=provider,
        goal_assessment="",
    )

    run_id = "run-20260101T000801-000801"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=1,
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "validation" in result.reason


def test_revision_cycle_limit_yields_paused_not_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, limits={"max_revision_cycles": 1}, provider=provider)

    run_id = "run-20260101T000801-000801"
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
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-leaf"],
                        "issue": "Needs work.",
                        "recommended_change": "Improve output.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
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
                findings=[
                    {
                        "id": "finding-02",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-leaf"],
                        "issue": "Still needs work.",
                        "recommended_change": "Improve again.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome is None
    assert "max_revision_cycles" in (result.reason or "")

    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "limit_exhausted"


def test_provider_exception_does_not_set_outcome(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)

    provider.script_turn([{"type": "error", "text": "provider crashed"}])
    with pytest.raises(ProviderRunError, match="provider crashed"):
        WholeOutputReviewOrchestrator(store, "run-20260101T000801-000801", provider).run()

    run = store.load_run("run-20260101T000801-000801")
    assert run["phase"] == WHOLE_OUTPUT_REVIEW
    assert run["outcome"] is None
    assert run["status"] == "running"


def test_whole_output_review_respond_uses_output_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    save_review_payload(store, "run-20260101T000801-000801", {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "finding_set_id": "review-whole-output-01-fs-01",
            "lifecycle_status": "review_pending",
            "active_stage": "initial_review",
        },
    )

    service = ReviewAgentService(store, "run-20260101T000801-000801")
    token = grant_capability(
        store,
        "run-20260101T000801-000801",
        role="reviewer",
        phase=WHOLE_OUTPUT_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-output-01",
    )
    with pytest.raises(RequestError, match="does not match current output revision"):
        service.respond(
            _review_respond_request(
                decision="approved",
                target_revision=0,
                store=store,
                run_id="run-20260101T000801-000801",
            ),
            capability_token=token,
        )


def test_whole_output_review_resumes_interrupted_producer_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    save_review_payload(store, run_id, {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "revision_cycles": 1,
            "lifecycle_status": "verification_pending",
            "active_stage": "finding_verification",
            "finding_set_id": "review-whole-output-01-fs-01",
            "review_record_schema_version": 2,
            "review_contract_version": 2,
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing.",
                    "recommended_change": "Add artifact reference.",
                    "status": "unresolved",
                }
            ],
        },
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    run["stop"] = None
    run["sessions"] = sessions_with_primary_session(producer=producer_session_id)
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")
    apply_production(
        store,
        run_id,
        {
            "production_revision": 2,
            "evidence_revision": True,
            "plan_items": ["item-leaf"],
            "dispositions": {
                "item-leaf": {
                    "disposition": "completed",
                    "evidence": "Added artifact reference.",
                }
            },
            "outputs": [
                {
                    "id": "output-leaf",
                    "type": "artifact",
                    "ref": "artifacts/leaf.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-leaf",
                    "output_refs": ["output-leaf"],
                    "summary": "Revised evidence.",
                }
            ],
            "summary": "Addressed reviewer finding.",
        },
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    apply_production(
        store,
        run_id,
        {
            "goal_assessment": "Output goal is fully met after revision.",
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    script_verification_then_scope_review_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=2,
        finding_set_id="review-whole-output-01-fs-01",
        finding_results=[
            {
                "finding_id": "finding-01",
                "disposition": "resolved",
                "evidence": ["artifact added"],
                "direct_side_effects": [],
            }
        ],
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    assert result.outcome == "accepted"
    assert store.load_run(run_id)["status"] == "completed"


def test_default_whole_output_rubric_covers_correctness_themes() -> None:
    from top_down_planning.config.defaults import DEFAULT_CONFIG

    rubric = DEFAULT_CONFIG["review"]["whole_output"]["rubric"]
    joined = "\n".join(rubric).casefold()
    for theme in (
        "plan conformance",
        "evidence correctness",
        "cross-output consistency",
        "completion claim",
        "traceability",
        "plan risk coverage",
    ):
        assert theme in joined, f"missing advisory theme {theme!r} in {rubric}"


def test_whole_output_package_includes_contract_v2_rubric_fields(tmp_path: Path) -> None:
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.orchestrator.whole_output_review import (
        build_whole_output_review_package,
    )
    from top_down_planning.orchestrator.review_analysis_context import (
        WHOLE_OUTPUT_AUDIT_PASS_IDS,
    )
    from tests.helpers import make_review_loop

    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    run_id = "run-20260101T000801-000801"
    plan = store.load_plan_model(run_id)
    config = store.load_resolved_config(run_id)
    production = store.load_production(run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_output"},
        review_record_schema_version=2,
        review_contract_version=2,
    )
    package = build_whole_output_review_package(
        run_id,
        store.load_run(run_id),
        config,
        plan,
        production,
        loop,
    )
    rubric_texts = [item["text"] for item in package["rubric_items"]]
    assert rubric_texts == DEFAULT_CONFIG["review"]["whole_output"]["rubric"]
    assert package["required_audit_passes"] == list(WHOLE_OUTPUT_AUDIT_PASS_IDS)
    assert package["review_contract_version"] == 2
    assert package["family_protocol_enabled"] is True
    assert "review-respond-family-discovery-output" in package["tool_instructions"]["examples"]
    protocol = package["protocol_instructions"].lower()
    assert "primary gate focus" in protocol
    assert "correctness" in protocol


def test_output_owner_request_includes_artifact_binding(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.whole_output_review import OutputWholeReviewAdapter
    from tests.helpers import make_review_loop

    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    run_id = "run-20260101T000801-000801"
    production = store.load_production(run_id)
    output_digest = mandatory_output_digest(store, run_id)
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=int(production["output_revision"]),
        scope={"kind": "whole_output"},
        review_record_schema_version=2,
        review_contract_version=2,
        finding_set_id="review-whole-output-01-fs-01",
        findings=[
            {
                "id": "finding-01",
                "severity": "blocker",
                "category": "correctness",
                "target_refs": ["item-leaf"],
                "issue": "Missing evidence.",
                "recommended_change": "Add evidence.",
                "status": "unresolved",
            }
        ],
    )
    adapter = OutputWholeReviewAdapter(store, run_id)
    config = store.load_resolved_config(run_id)
    request = adapter.build_owner_request(loop, config, "revision")
    expected = __import__(
        "top_down_planning.domain.reviews",
        fromlist=["primary_review_resume_fields"],
    ).primary_review_resume_fields(
        loop,
        config=config,
        artifact_revision=int(production["output_revision"]),
        artifact_digest=output_digest,
    )
    assert request["active_families"] == expected["active_families"]
    assert request["audit_passes_completed"] == expected["audit_passes_completed"]


def test_whole_output_package_uses_current_digest_for_family_view_when_run_digest_stale(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.whole_output_review import (
        build_whole_output_review_package,
    )

    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    run_id = "run-20260101T000801-000801"

    production = store.load_production(run_id)
    current_revision = int(production["output_revision"])
    current_digest = mandatory_output_digest(store, run_id)
    run = store.load_run(run_id)
    digests = dict(run.get("digests") or {})
    digests["output"] = "stale-output-digest-00000000"
    run = dict(run)
    run["digests"] = digests
    atomic_write_json(store.run_dir(run_id) / "run.json", run)
    assert digests["output"] != current_digest

    finding = ReviewFinding(
        id="finding-01",
        severity="blocker",
        category="correctness",
        target_refs=["item-leaf"],
        issue="Output evidence is missing.",
        recommended_change="Add artifact reference.",
        family_id="family-output-01",
    )
    family = FindingFamily(
        id="family-output-01",
        finding_set_id="review-whole-output-01-fs-01",
        rule_id="custom.evidence-gap",
        subject_key="leaf-evidence",
        scope_kind="whole-output",
        rule_definition="output evidence completeness gap",
        family_fingerprint=compute_family_fingerprint(
            rule_id="custom.evidence-gap",
            subject_key="leaf-evidence",
            scope_kind="whole-output",
            rule_definition="output evidence completeness gap",
        ),
        title="Evidence gap",
        seed_finding_id="finding-01",
        confirmed_finding_ids=["finding-01"],
        candidate_refs=[],
        recommended_change="Add artifact reference.",
    )
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        revise_at="blocker",
        target_revision=current_revision,
        scope={"kind": "whole_output"},
        status="pending",
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="review-whole-output-01-fs-01",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"review-whole-output-01-fs-01": ["finding-01"]},
        family_sweeps=[
            {
                "id": "sweep-owner-01",
                "family_id": "family-output-01",
                "finding_set_id": "review-whole-output-01-fs-01",
                "stage": "owner_fix",
                "artifact_revision": current_revision,
                "artifact_digest": current_digest,
                "actor_role": "producer",
                "searched_refs": ["production:*"],
                "search_dimensions": ["evidence"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "No remaining evidence gaps.",
            }
        ],
        finding_actions=[
            {
                "finding_id": "finding-01",
                "finding_set_id": "review-whole-output-01-fs-01",
                "action": "fix",
                "actor_role": "producer",
                "artifact_revision": current_revision,
                "rationale": "Added evidence.",
            }
        ],
        reviewer_session_id="stub-session-output-reviewer",
        review_record_schema_version=2,
        review_contract_version=2,
    )
    package = build_whole_output_review_package(
        run_id,
        store.load_run(run_id),
        store.load_resolved_config(run_id),
        store.load_plan_model(run_id),
        production,
        loop,
    )
    family_view = package["family_verification_view"]["families"][0]
    assert family_view["operational_status"] != "owner_sweep_pending"


def test_whole_output_review_v2_family_owner_sweep_e2e_reaches_accepted(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    loop_id = "review-whole-output-01"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    findings = [
        {
            "id": "finding-01",
            "severity": "blocker",
            "category": "correctness",
            "target_refs": ["item-leaf"],
            "issue": "Output evidence is missing.",
            "recommended_change": "Add artifact reference.",
            "status": "unresolved",
        }
    ]

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_output",
                decision="changes_requested",
                findings=findings,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        ),
    )

    def _producer_revision() -> None:
        apply_production(
            store,
            run_id,
            {
                "production_revision": 2,
                "evidence_revision": True,
                "plan_items": ["item-leaf"],
                "dispositions": {
                    "item-leaf": {
                        "disposition": "completed",
                        "evidence": "Added artifact reference.",
                    }
                },
                "outputs": [
                    {
                        "id": "output-leaf",
                        "type": "artifact",
                        "ref": "artifacts/leaf.txt",
                    }
                ],
                "contributions": [
                    {
                        "item_id": "item-leaf",
                        "output_refs": ["output-leaf"],
                        "summary": "Revised evidence.",
                    }
                ],
                "summary": "Addressed reviewer finding.",
            },
            handler="apply",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        apply_production(
            store,
            run_id,
            {
                "goal_assessment": "Output goal is fully met after revision.",
            },
            handler="submit_completion",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        new_revision = int(store.load_production(run_id)["output_revision"])
        new_digest = mandatory_output_digest(store, run_id)
        loop_payload = store.load_review(run_id, loop_id)
        families = loop_payload.get("finding_families") or []
        assert families, "discovery should persist finding families on the loop"
        family_id = str(families[0]["id"])
        record_finding_actions(
            store,
            run_id,
            {
                "loop_id": loop_id,
                "target_revision": new_revision,
                "target_digest": new_digest,
                "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
                "family_fixes": [
                    {
                        "family_id": family_id,
                        "target_finding_ids": [],
                        "rationale": "Added missing evidence across production.",
                        "changed_refs": ["item-leaf"],
                        "owner_sweep": {
                            "searched_refs": ["production:*"],
                            "search_dimensions": ["evidence"],
                            "additional_fixed_refs": [],
                            "remaining_instance_refs": [],
                            "completed": True,
                            "summary": "No remaining evidence gaps.",
                        },
                    }
                ],
                "finding_actions": [],
            },
            role="producer",
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()
        loop_after_record = store.load_review(run_id, loop_id)
        assert any(
            sweep.get("stage") == "owner_fix"
            for sweep in loop_after_record.get("family_sweeps", [])
        )

    provider.script_turn(done_events(text="turn complete"), mutate_store=_producer_revision)

    def _verification_respond() -> None:
        loop = store.load_review(run_id, loop_id)
        finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
        target_revision = int(store.load_production(run_id)["output_revision"])
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_type="whole_output",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["artifact added"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_verification_respond)

    def _scope_respond() -> None:
        target_revision = int(store.load_production(run_id)["output_revision"])
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_respond)

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    assert result.outcome == "accepted"
    review = store.load_review(run_id, loop_id)
    assert review.get("active_stage") == "scope_review"
    assert review.get("status") == "approved"
    assert review.get("verification_result")
    assert review.get("scope_review_result")
    assert review.get("finding_families")
    owner_sweeps = [
        sweep
        for sweep in review.get("family_sweeps", [])
        if sweep.get("stage") == "owner_fix"
    ]
    assert owner_sweeps
    assert owner_sweeps[-1]["artifact_revision"] == int(
        store.load_production(run_id)["output_revision"]
    )
    assert owner_sweeps[-1]["artifact_digest"] == mandatory_output_digest(store, run_id)
    events = store.load_events(run_id)
    event_types = {event.get("type") for event in events}
    assert "whole_output_scope_review_started" in event_types


def test_prepare_recheck_preserves_owner_family_sweeps_after_record_actions(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    loop_id = "review-whole-output-01"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    finding = ReviewFinding(
        id="finding-01",
        severity="blocker",
        category="correctness",
        target_refs=["item-leaf"],
        issue="Output evidence is missing.",
        recommended_change="Add artifact reference.",
        family_id="family-output-01",
    )
    family = FindingFamily(
        id="family-output-01",
        finding_set_id="review-whole-output-01-fs-01",
        rule_id="custom.evidence-gap",
        subject_key="leaf-evidence",
        scope_kind="whole-output",
        rule_definition="output evidence completeness gap",
        family_fingerprint=compute_family_fingerprint(
            rule_id="custom.evidence-gap",
            subject_key="leaf-evidence",
            scope_kind="whole-output",
            rule_definition="output evidence completeness gap",
        ),
        title="Evidence gap",
        seed_finding_id="finding-01",
        confirmed_finding_ids=["finding-01"],
        candidate_refs=[],
        recommended_change="Add artifact reference.",
    )
    discovery_loop = make_review_loop(
        id=loop_id,
        type="whole_output",
        revise_at="blocker",
        target_revision=1,
        scope={"kind": "whole_output"},
        status="changes_requested",
        lifecycle_status="findings_open",
        finding_set_id="review-whole-output-01-fs-01",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"review-whole-output-01-fs-01": ["finding-01"]},
        reviewer_session_id="stub-session-output-reviewer",
        review_record_schema_version=2,
        review_contract_version=2,
    )
    save_review_payload(store, run_id, discovery_loop.to_dict())

    stale_loop = enter_owner_revision_cycle(replace(discovery_loop, revision_cycles=1))
    save_review_payload(store, run_id, stale_loop.to_dict())

    apply_production(
        store,
        run_id,
        {
            "production_revision": 2,
            "evidence_revision": True,
            "plan_items": ["item-leaf"],
            "dispositions": {
                "item-leaf": {
                    "disposition": "completed",
                    "evidence": "Added artifact reference.",
                }
            },
            "outputs": [
                {
                    "id": "output-leaf",
                    "type": "artifact",
                    "ref": "artifacts/leaf.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-leaf",
                    "output_refs": ["output-leaf"],
                    "summary": "Revised evidence.",
                }
            ],
            "summary": "Addressed reviewer finding.",
        },
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    new_revision = int(store.load_production(run_id)["output_revision"])
    new_digest = mandatory_output_digest(store, run_id)
    record_finding_actions(
        store,
        run_id,
        {
            "loop_id": loop_id,
            "target_revision": new_revision,
            "target_digest": new_digest,
            "finding_set_id": str(store.load_review(run_id, loop_id).get("finding_set_id") or ""),
            "family_fixes": [
                {
                    "family_id": "family-output-01",
                    "target_finding_ids": [],
                    "rationale": "Added missing evidence across production.",
                    "changed_refs": ["item-leaf"],
                    "owner_sweep": {
                        "searched_refs": ["production:*"],
                        "search_dimensions": ["evidence"],
                        "additional_fixed_refs": [],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "No remaining evidence gaps.",
                    },
                }
            ],
            "finding_actions": [],
        },
        role="producer",
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id=loop_id,
    )()

    stored_before_recheck = store.load_review(run_id, loop_id)
    owner_sweeps_before = [
        sweep
        for sweep in stored_before_recheck.get("family_sweeps", [])
        if sweep.get("stage") == "owner_fix"
    ]
    assert owner_sweeps_before
    assert owner_sweeps_before[-1]["artifact_revision"] == new_revision
    assert owner_sweeps_before[-1]["artifact_digest"] == new_digest

    orchestrator = WholeOutputReviewOrchestrator(store, run_id, provider)
    with patch(
        "top_down_planning.orchestrator.review_loop_driver.deliver_reviewer_turn",
        return_value="stub-session-output-reviewer",
    ):
        with patch(
            "top_down_planning.orchestrator.review_loop_driver.emit_reviewer_session_resumed"
        ):
            orchestrator._driver._prepare_recheck(stale_loop)

    stored_after_recheck = store.load_review(run_id, loop_id)
    owner_sweeps_after = [
        sweep
        for sweep in stored_after_recheck.get("family_sweeps", [])
        if sweep.get("stage") == "owner_fix"
    ]
    assert owner_sweeps_after
    assert owner_sweeps_after[-1]["artifact_revision"] == new_revision
    assert owner_sweeps_after[-1]["artifact_digest"] == new_digest
    assert stored_after_recheck.get("target_revision") == new_revision


def test_persist_loop_rejects_stale_loop_revision_after_store_advanced(
    tmp_path: Path,
) -> None:
    from core_tools.persistence import StoreRevisionConflictError
    from top_down_planning.orchestrator.mandatory_review_stages import (
        mark_verification_pending,
    )
    from top_down_planning.persistence.review_commit import (
        review_record_revision,
        save_review_with_expected_revision,
    )

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    loop_id = "review-whole-output-01"

    loop = make_review_loop(
        id=loop_id,
        type="whole_output",
        revise_at="blocker",
        target_revision=1,
        scope={"kind": "whole_output"},
        status="pending",
        lifecycle_status="revision_in_progress",
        finding_set_id="review-whole-output-01-fs-01",
        reviewer_session_id="stub-session-output-reviewer",
        review_record_schema_version=2,
        review_contract_version=2,
    )
    save_review_with_expected_revision(
        store,
        run_id,
        loop.to_dict(),
        expected_revision=review_record_revision(store.load_review(run_id, loop_id)),
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))

    driver = WholeOutputReviewOrchestrator(store, run_id, provider)._driver
    loop = driver._persist_loop(loop)

    save_review_with_expected_revision(
        store,
        run_id,
        loop,
        expected_revision=loop.revision,
    )

    stale_loop = loop
    artifact_revision, _digest = driver._adapter.current_artifact_binding()
    stale_transition = mark_verification_pending(
        stale_loop,
        target_revision=artifact_revision,
    )

    with pytest.raises(StoreRevisionConflictError):
        driver._persist_loop(stale_transition)
