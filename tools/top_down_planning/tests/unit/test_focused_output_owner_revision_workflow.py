"""Focused-output owner revision, evidence_revision, and blocker orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.agent_tool import ProductionAgentService, RequestError, ReviewAgentService
from top_down_planning.domain.production_blockers import (
    BLOCKER_KIND_EXTERNAL,
    BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
    BLOCKER_STATUS_RESOLVED,
)
from top_down_planning.domain.reviews import (
    ReviewLoop,
    focused_output_evidence_revision_allowed,
    focused_output_owner_revision_in_progress_loop,
    focused_output_revision_transaction_active,
    focused_output_revision_transaction_active_loop,
    focused_output_revision_target_ids,
    mark_advisory_handoff_incomplete,
    prepare_review_incomplete_retry,
)
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.orchestrator.focused_review import (
    FocusedReviewAdapter,
    FocusedReviewOrchestrator,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.provider_turns import (
    find_pending_focused_review_loop_id,
    find_resumable_focused_review_loop_id,
    owner_revision_complete,
)
from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_production,
    done_events,
    grant_capability,
    mandatory_output_digest,
    record_finding_actions,
    request_focused_review,
    respond_review,
    review_loop_dict_with_binding,
    save_review_payload,
)
from tests.support.focused_evidence_revision import (
    create_agent_focused_test_run_open_item_second,
    create_focused_evidence_test_run,
    focused_output_review_payload,
)
from tests.support.focused_review import (
    create_production_run,
    create_production_run_open_item_second,
    review_respond_request,
)


def _owner_revision_pending_loop(*, item_ids: list[str]) -> dict:
    binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("ended-reviewer-session")
    loop = review_loop_dict_with_binding(
        {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": item_ids},
            "status": "pending",
            "revise_at": "blocker",
            "revision_cycles": 1,
            "finding_set_id": "fs-owner-revision-01",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": item_ids[:1],
                    "issue": "Need better evidence.",
                    "recommended_change": "Revise artifact.",
                    "status": "unresolved",
                }
            ],
        }
    )
    loop["reviewer_binding"] = binding.to_dict()
    return loop


def _advisory_optional_focused_output_loop(*, item_ids: list[str]) -> dict:
    binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("reviewer-sess-advisory")
    loop = review_loop_dict_with_binding(
        {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": item_ids},
            "status": "advisory_pending",
            "revise_at": "blocker",
            "revision_cycles": 0,
            "finding_set_id": "fs-advisory-01",
            "findings": [
                {
                    "id": "finding-opt",
                    "severity": "minor",
                    "category": "correctness",
                    "target_refs": item_ids[:1],
                    "issue": "Optional polish.",
                    "recommended_change": "Improve wording.",
                    "status": "unresolved",
                }
            ],
            "finding_actions": [],
        }
    )
    loop["reviewer_binding"] = binding.to_dict()
    return loop


def _normal_apply_item_second_request(store: FileRunStore, run_id: str) -> dict:
    return {
        "production_revision": int(store.load_production(run_id)["revision"]),
        "plan_items": ["item-second"],
        "dispositions": {
            "item-second": {
                "disposition": "completed",
                "evidence": "Unrelated normal apply during focused review.",
            }
        },
        "outputs": [
            {
                "id": "output-second-race",
                "type": "artifact",
                "ref": "artifacts/second.txt",
            }
        ],
        "contributions": [
            {
                "item_id": "item-second",
                "output_refs": ["output-second-race"],
                "summary": "Race batch.",
            }
        ],
        "summary": "Unrelated normal apply.",
    }

def test_evidence_revision_allowed_after_owner_actions_recorded_before_artifact(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import owner_revision_complete

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    create_focused_evidence_test_run(store)
    loop_payload = _owner_revision_pending_loop(item_ids=["item-first"])
    loop_payload["finding_actions"] = [
        {
            "finding_id": "finding-01",
            "finding_set_id": "fs-owner-revision-01",
            "action": "fix",
            "actor_role": "producer",
            "owner_revision_cycle": 1,
            "artifact_revision": 1,
            "rationale": "Evidence revision will follow.",
        }
    ]
    save_review_payload(store, run_id, loop_payload)
    loop = ReviewLoop.from_dict(store.load_review(run_id, "review-focused-output-01"))
    assert owner_revision_complete(store, run_id, loop.id) is True
    assert focused_output_evidence_revision_allowed(
        loop, store=store, run_id=run_id
    )
    assert (
        find_pending_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        is None
    )
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    result = ProductionAgentService(store, run_id).apply(
        {
            "production_revision": 1,
            "evidence_revision": True,
            "focused_review_loop_id": "review-focused-output-01",
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact.",
                }
            },
            "outputs": [
                {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Evidence after owner actions.",
                }
            ],
            "summary": "Focused evidence revision.",
        },
        capability_token=token,
    )
    assert result["ok"] is True
    assert int(store.load_production(run_id)["output_revision"]) == 2
    assert (
        find_pending_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        == "review-focused-output-01"
    )


def test_active_wait_blocker_runs_focused_review_before_pause(tmp_path: Path) -> None:
    from tests.helpers import make_review_loop

    from top_down_planning.orchestrator import production as production_module
    from top_down_planning.orchestrator.provider_turns import (
        restore_primary_capability_after_focused_review,
    )

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    loop_id = "review-focused-output-01"
    loop = make_review_loop(
        id=loop_id,
        type="focused_output",
        target_revision=int(store.load_production(run_id)["output_revision"]),
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="pending",
        reviewer_session_id="sess-fr",
    )
    save_review_payload(store, run_id, loop.to_dict())
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
        "status": "active",
        "review_loop_id": loop_id,
        "target_revision": int(production["output_revision"]),
        "evidence": "Waiting on focused review.",
        "affected_refs": ["item-first"],
        "summary": "focused review pending",
    }
    store.save_production(run_id, updated, expected)
    provider.script_session_turn(
        "sess-fr",
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                decision="approved",
            ),
            phase=PRODUCTION,
            loop_id=loop_id,
        ),
    )

    orchestrator = ProductionPhaseOrchestrator(store, run_id, provider)
    session_id = "stub-session-1"
    order: list[str] = []

    def tracked_restore(*args: object, **kwargs: object) -> object:
        order.append("restore")
        return restore_primary_capability_after_focused_review(*args, **kwargs)

    assert orchestrator._terminate_if_terminal_blocker(session_id) is None
    blocker = orchestrator._evaluate_blocker_report()
    assert blocker.disposition == "active_wait"

    with patch.object(
        production_module,
        "restore_primary_capability_after_focused_review",
        side_effect=tracked_restore,
    ):
        orchestrator._capability_token = (
            production_module.restore_primary_capability_after_focused_review(
                store,
                run_id,
                provider,
                review_type="focused_output",
                role="producer",
                current_token=None,
            )
        ).capability_token

    assert order == ["restore"]
    assert store.load_review(run_id, loop_id)["status"] == "approved"
    after = orchestrator._handle_blocker_after_focused_review(session_id)
    assert after is None
    report = store.load_production(run_id).get("blocker_report") or {}
    assert report.get("status") == BLOCKER_STATUS_RESOLVED


def test_focused_evidence_revision_allowed_after_owner_revision_handoff(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    create_focused_evidence_test_run(store)
    save_review_payload(
        store,
        "run-20260101T000551-000551",
        _owner_revision_pending_loop(item_ids=["item-first"]),
    )
    loop = ReviewLoop.from_dict(
        store.load_review("run-20260101T000551-000551", "review-focused-output-01")
    )
    assert focused_output_evidence_revision_allowed(
        loop, store=store, run_id="run-20260101T000551-000551"
    )
    assert focused_output_revision_target_ids(
        [loop.to_dict()],
        loop_id=loop.id,
        store=store,
        run_id="run-20260101T000551-000551",
    ) == {"item-first"}


def test_normal_production_apply_rejected_during_focused_output_owner_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    create_agent_focused_test_run_open_item_second(store, run_id=run_id)
    save_review_payload(store, run_id, _owner_revision_pending_loop(item_ids=["item-first"]))
    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    production_revision = int(store.load_production(run_id)["revision"])

    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            {
                "production_revision": production_revision,
                "plan_items": ["item-second"],
                "dispositions": {
                    "item-second": {
                        "disposition": "completed",
                        "evidence": "Unrelated work.",
                    }
                },
                "outputs": [
                    {"id": "output-second-v2", "type": "artifact", "ref": "second.txt"}
                ],
                "contributions": [
                    {
                        "item_id": "item-second",
                        "output_refs": ["output-second-v2"],
                        "summary": "Unrelated item during owner revision.",
                    }
                ],
                "summary": "Should be rejected.",
            },
            capability_token=token,
        )

    assert int(store.load_production(run_id)["output_revision"]) == 1


def test_evidence_revision_then_owner_actions_before_reviewer_recheck(
    tmp_path: Path,
) -> None:
    from top_down_planning.domain.reviews import (
        focused_review_owner_actions_complete,
        focused_review_owner_artifact_revision_pending,
        focused_review_producer_owner_work_pending,
    )
    from top_down_planning.orchestrator.provider_turns import owner_revision_complete

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    create_focused_evidence_test_run(store)
    save_review_payload(store, run_id, _owner_revision_pending_loop(item_ids=["item-first"]))
    loop_id = "review-focused-output-01"
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)

    result = service.apply(
        {
            "production_revision": 1,
            "evidence_revision": True,
            "focused_review_loop_id": loop_id,
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact.",
                }
            },
            "outputs": [
                {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Evidence before owner actions.",
                }
            ],
            "summary": "Focused evidence revision first.",
        },
        capability_token=token,
    )
    assert result["ok"] is True
    assert int(store.load_production(run_id)["output_revision"]) == 2

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert focused_review_owner_artifact_revision_pending(
        loop, store=store, run_id=run_id
    ) is False
    assert focused_review_owner_actions_complete(loop) is False
    assert (
        find_pending_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        is None
    )

    record_finding_actions(
        store,
        run_id,
        {
            "loop_id": loop_id,
            "finding_set_id": "fs-owner-revision-01",
            "finding_actions": [
                {
                    "finding_id": "finding-01",
                    "action": "fix",
                    "actor_role": "producer",
                    "rationale": "Evidence revision completed.",
                }
            ],
        },
        role="producer",
        phase=PRODUCTION,
        loop_id=loop_id,
    )()

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert owner_revision_complete(store, run_id, loop_id) is True
    assert focused_review_producer_owner_work_pending(
        loop, store=store, run_id=run_id
    ) is False


def test_focused_owner_revision_allows_evidence_apply_then_blocks_unrelated_normal_apply(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    create_agent_focused_test_run_open_item_second(store, run_id=run_id)
    save_review_payload(store, run_id, _owner_revision_pending_loop(item_ids=["item-first"]))
    loop_id = "review-focused-output-01"
    first_v2 = tmp_path / "first-v2.txt"
    first_v2.write_text("revised", encoding="utf-8")
    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    evidence = service.apply(
        {
            "production_revision": 1,
            "evidence_revision": True,
            "focused_review_loop_id": loop_id,
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact.",
                }
            },
            "outputs": [
                {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Focused evidence revision.",
                }
            ],
            "summary": "Evidence revision for item-first.",
        },
        capability_token=token,
    )
    assert evidence["ok"] is True
    assert int(store.load_production(run_id)["output_revision"]) == 2

    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "plan_items": ["item-second"],
                "dispositions": {
                    "item-second": {
                        "disposition": "completed",
                        "evidence": "Unrelated.",
                    }
                },
                "outputs": [
                    {"id": "output-second-v2", "type": "artifact", "ref": "second.txt"}
                ],
                "contributions": [
                    {
                        "item_id": "item-second",
                        "output_refs": ["output-second-v2"],
                        "summary": "Still blocked until owner actions.",
                    }
                ],
                "summary": "Unrelated normal apply.",
            },
            capability_token=token,
        )


def test_focused_evidence_revision_apply_after_owner_handoff(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    create_focused_evidence_test_run(store)
    save_review_payload(store, run_id, _owner_revision_pending_loop(item_ids=["item-first"]))
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    result = service.apply(
        {
            "production_revision": 1,
            "evidence_revision": True,
            "focused_review_loop_id": "review-focused-output-01",
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact.",
                }
            },
            "outputs": [
                {"id": "output-first-v2", "type": "artifact", "ref": "first-v2.txt"}
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Addressed focused finding.",
                }
            ],
            "summary": "Focused evidence revision.",
        },
        capability_token=token,
    )

    assert result["ok"] is True
    assert int(store.load_production(run_id)["output_revision"]) == 2


def test_fresh_pending_focused_review_rejects_evidence_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    create_focused_evidence_test_run(store)
    fresh = focused_output_review_payload(item_ids=["item-first"], status="pending")
    fresh["revision_cycles"] = 0
    fresh["findings"] = []
    save_review_payload(store, run_id, fresh)
    loop = ReviewLoop.from_dict(store.load_review(run_id, "review-focused-output-01"))
    assert focused_output_evidence_revision_allowed(loop) is False
    assert (
        focused_output_revision_target_ids(
            [loop.to_dict()],
            loop_id=loop.id,
            store=store,
            run_id=run_id,
        )
        == set()
    )


def test_resolved_findings_do_not_authorize_revision_targets() -> None:
    payload = _owner_revision_pending_loop(item_ids=["item-first"])
    payload["findings"] = [
        {
            **payload["findings"][0],
            "status": "resolved",
        }
    ]
    loop = ReviewLoop.from_dict(payload)
    assert focused_output_revision_target_ids([loop.to_dict()], loop_id=loop.id) == set()


def test_find_pending_focused_review_skips_owner_revision_in_progress(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000501-000501"
    create_production_run(store)
    save_review_payload(store, run_id, _owner_revision_pending_loop(item_ids=["item-first"]))
    assert (
        find_pending_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        is None
    )


def test_external_blocker_after_owner_handoff_does_not_fail_run(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()

    def _reject_unknown(session_id: str) -> None:
        if session_id == "ended-reviewer-session":
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )

    provider._canonical_session_id = provider.canonical_session_id  # type: ignore[attr-defined]
    original_canonical = provider.canonical_session_id

    def canonical(session_id: str) -> str:
        _reject_unknown(session_id)
        return original_canonical(session_id)

    provider.canonical_session_id = canonical  # type: ignore[method-assign]

    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    respond_review(
        store,
        run_id,
        review_respond_request(
            store,
            run_id,
            loop_id="review-focused-output-01",
            decision="changes_requested",
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-first"],
                    "issue": "Need better evidence.",
                    "recommended_change": "Revise artifact.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=PRODUCTION,
        loop_id="review-focused-output-01",
    )()
    loop_payload = store.load_review(run_id, "review-focused-output-01")
    binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("ended-reviewer-session")
    loop = ReviewLoop.from_dict(
        {
            **loop_payload,
            "status": "pending",
            "revision_cycles": 1,
            "reviewer_binding": binding.to_dict(),
        }
    )
    save_review_payload(store, run_id, loop.to_dict())

    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    ProductionAgentService(store, run_id).report_blocked(
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "kind": BLOCKER_KIND_EXTERNAL,
            "evidence": "Vendor API unavailable.",
            "affected_refs": ["item-first"],
            "summary": "external outage",
        },
        capability_token=token,
    )

    provider.script_session_turn(
        producer_session_id,
        done_events(text="after blocker"),
    )
    result = ProductionPhaseOrchestrator(store, run_id, provider).run()
    run = store.load_run(run_id)

    assert result.ok is False
    assert run["status"] == "completed"
    assert run["outcome"] == "blocked"
    assert (run.get("stop") or {}).get("code") != "orchestrator_invariant_failure"


def test_focused_orchestrator_does_not_resume_ended_reviewer_during_owner_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000501-000501"
    provider = StubProvider()

    def _reject_unknown(session_id: str) -> None:
        if session_id == "ended-reviewer-session":
            raise ProviderSessionError(
                f"unknown provider session: {session_id}",
                session_id=session_id,
            )

    original_canonical = provider.canonical_session_id

    def canonical(session_id: str) -> str:
        _reject_unknown(session_id)
        return original_canonical(session_id)

    provider.canonical_session_id = canonical  # type: ignore[method-assign]
    create_production_run(store, provider=provider)
    save_review_payload(store, run_id, _owner_revision_pending_loop(item_ids=["item-first"]))

    result = FocusedReviewOrchestrator(store, run_id, provider).run(
        "review-focused-output-01"
    )

    assert result.ok is False
    assert "owner revision" in (result.reason or "").lower()


def test_focused_owner_revision_recheck_then_normal_production_resumes(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000501-000501"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    ProductionAgentService(store, run_id).report_blocked(
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
            "review_loop_id": loop_id,
            "evidence": "Waiting on focused review.",
            "affected_refs": ["item-first"],
            "summary": "focused review pending",
        },
        capability_token=token,
    )
    respond_review(
        store,
        run_id,
        review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            decision="changes_requested",
            target_revision=int(store.load_review(run_id, loop_id)["target_revision"]),
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-first"],
                    "issue": "Evidence is incomplete.",
                    "recommended_change": "Add a revised artifact.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=PRODUCTION,
        loop_id=loop_id,
    )()

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    entered = adapter.enter_revision_cycle(
        loop,
        max(1, int(loop.revision_cycles) + 1),
    )
    save_review_payload(store, run_id, entered.to_dict())
    output_revision_before = int(store.load_production(run_id)["output_revision"])
    service = ProductionAgentService(store, run_id)

    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "plan_items": ["item-second"],
                "dispositions": {
                    "item-second": {
                        "disposition": "completed",
                        "evidence": "Unrelated batch during owner revision.",
                    }
                },
                "outputs": [
                    {
                        "id": "output-second-batch",
                        "type": "artifact",
                        "ref": "artifacts/second.txt",
                    }
                ],
                "contributions": [
                    {
                        "item_id": "item-second",
                        "output_refs": ["output-second-batch"],
                        "summary": "Should be rejected during owner revision.",
                    }
                ],
                "summary": "Unrelated normal apply.",
            },
            capability_token=token,
        )

    workspace = Path(str(store.load_run(run_id)["workspace"]))
    (workspace / "artifacts" / "first-v2.txt").write_text("revised", encoding="utf-8")
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "evidence_revision": True,
            "focused_review_loop_id": loop_id,
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact for reviewer.",
                }
            },
            "outputs": [
                {
                    "id": "output-first-v2",
                    "type": "artifact",
                    "ref": "artifacts/first-v2.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Focused evidence revision.",
                }
            ],
            "summary": "Evidence revision for focused-output review finding.",
        },
        handler="apply",
    )()
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_before + 1

    loop_payload = store.load_review(run_id, loop_id)
    record_finding_actions(
        store,
        run_id,
        {
            "loop_id": loop_id,
            "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
            "finding_actions": [
                {
                    "finding_id": "finding-01",
                    "action": "fix",
                    "actor_role": "producer",
                    "rationale": "Added a revised artifact.",
                }
            ],
        },
        role="producer",
        phase=PRODUCTION,
        loop_id=loop_id,
    )()

    assert owner_revision_complete(store, run_id, loop_id) is True
    assert focused_output_owner_revision_in_progress_loop(store, run_id) is None
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None

    normal_item_second_request = {
        "production_revision": int(store.load_production(run_id)["revision"]),
        "plan_items": ["item-second"],
        "dispositions": {
            "item-second": {
                "disposition": "completed",
                "evidence": "Must wait for reviewer recheck.",
            }
        },
        "outputs": [
            {
                "id": "output-second-premature",
                "type": "artifact",
                "ref": "artifacts/second.txt",
            }
        ],
        "contributions": [
            {
                "item_id": "item-second",
                "output_refs": ["output-second-premature"],
                "summary": "Blocked until focused review closes.",
            }
        ],
        "summary": "Premature normal apply after owner work.",
    }
    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            normal_item_second_request,
            capability_token=grant_capability(
                store, run_id, role="producer", phase=PRODUCTION
            ),
        )

    reviewer_session_id = reviewer_loop_provider_session_id(
        store.load_review(run_id, loop_id)
    )

    def _verify_revised_artifact() -> None:
        loop = store.load_review(run_id, loop_id)
        respond_review(
            store,
            run_id,
            {
                "loop_id": loop_id,
                "target_revision": int(loop["target_revision"]),
                "stage": "finding_verification",
                "decision": "verified",
                "finding_set_id": str(loop.get("finding_set_id") or ""),
                "finding_results": [
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["revised artifact attached"],
                        "direct_side_effects": [],
                    }
                ],
                "new_direct_side_effect_findings": [],
                "target_digest": mandatory_output_digest(store, run_id),
                "summary": "focused verification",
            },
            phase=PRODUCTION,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="owner session rotate"))
    provider.script_turn(done_events(text="producer owner revision turn"))
    if reviewer_session_id:
        provider.script_session_turn(
            reviewer_session_id,
            done_events(text="recheck delivery without respond"),
        )
        provider.script_session_turn(
            reviewer_session_id,
            done_events(text="reviewer verify"),
            mutate_store=_verify_revised_artifact,
        )
    else:
        provider.script_turn(done_events(text="recheck delivery without respond"))
        provider.script_turn(
            done_events(text="reviewer verify"),
            mutate_store=_verify_revised_artifact,
        )

    recheck_result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)

    assert recheck_result.ok is True
    assert store.load_review(run_id, loop_id)["status"] == "approved"
    assert focused_output_revision_transaction_active_loop(store, run_id) is None
    assert any(
        event.get("type") == "focused_review_recheck_requested"
        and event.get("loop_id") == loop_id
        for event in store.load_events(run_id)
    )

    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-second"],
            "dispositions": {
                "item-second": {
                    "disposition": "completed",
                    "evidence": "Normal production after focused review closed.",
                }
            },
            "outputs": [
                {
                    "id": "output-second-done",
                    "type": "artifact",
                    "ref": "artifacts/second.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-second",
                    "output_refs": ["output-second-done"],
                    "summary": "Item second completed after recheck.",
                }
            ],
            "summary": "Normal batch after focused owner revision transaction.",
        },
        handler="apply",
    )()

    assert store.load_production(run_id)["dispositions"]["item-second"] == "completed"
    run = store.load_run(run_id)
    assert run.get("phase") == PRODUCTION
    assert run.get("status") == "running"


def test_focused_output_revision_transaction_active_for_advisory_and_revision_statuses() -> None:
    advisory = ReviewLoop.from_dict(
        _advisory_optional_focused_output_loop(item_ids=["item-first"])
    )
    assert focused_output_revision_transaction_active(advisory) is True

    needs_revision = replace(advisory, status="needs_revision")
    assert focused_output_revision_transaction_active(needs_revision) is True

    incomplete = replace(advisory, status="review_incomplete")
    assert focused_output_revision_transaction_active(incomplete) is True

    approved = replace(advisory, status="approved")
    assert focused_output_revision_transaction_active(approved) is False


def test_normal_apply_blocked_during_focused_output_advisory_pending(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000502-000502"
    provider = StubProvider()
    create_production_run_open_item_second(store, provider, run_id=run_id)
    save_review_payload(
        store,
        run_id,
        _advisory_optional_focused_output_loop(item_ids=["item-first"]),
    )
    output_revision_before = int(store.load_production(run_id)["output_revision"])
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            _normal_apply_item_second_request(store, run_id),
            capability_token=token,
        )
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_before


def test_focused_output_advisory_then_owner_revision_still_blocks_normal_apply(
    tmp_path: Path,
) -> None:
    """Optional finding advisory window and charged owner revision stay in one transaction."""
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000503-000503"
    provider = StubProvider()
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    save_review_payload(
        store,
        run_id,
        _advisory_optional_focused_output_loop(item_ids=["item-first"]),
    )
    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)

    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            _normal_apply_item_second_request(store, run_id),
            capability_token=token,
        )

    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "changes_requested"
    save_review_payload(store, run_id, loop_payload)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    entered = adapter.enter_revision_cycle(loop, 1)
    save_review_payload(store, run_id, entered.to_dict())
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None

    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            _normal_apply_item_second_request(store, run_id),
            capability_token=token,
        )

def test_focused_output_review_incomplete_keeps_transaction_until_retry(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000506-000506"
    provider = StubProvider()
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop = ReviewLoop.from_dict(
        _advisory_optional_focused_output_loop(item_ids=["item-first"])
    )
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())
    assert focused_output_revision_transaction_active(incomplete) is True
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            _normal_apply_item_second_request(store, run_id),
            capability_token=token,
        )

    retried = prepare_review_incomplete_retry(incomplete)
    assert retried.status == "advisory_pending"
    save_review_payload(store, run_id, retried.to_dict())
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None


def test_focused_output_orchestrator_advisory_defer_completes_and_allows_normal_apply(
    tmp_path: Path,
) -> None:
    from top_down_planning.persistence.session_bindings import primary_provider_session_id

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000504-000504"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    respond_review(
        store,
        run_id,
        review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            decision="approved",
            target_revision=int(store.load_review(run_id, loop_id)["target_revision"]),
            findings=[
                {
                    "id": "finding-opt",
                    "severity": "minor",
                    "category": "correctness",
                    "target_refs": ["item-first"],
                    "issue": "Optional polish.",
                    "recommended_change": "Improve wording.",
                }
            ],
        ),
        phase=PRODUCTION,
        loop_id=loop_id,
    )()
    assert store.load_review(run_id, loop_id)["status"] == "advisory_pending"
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None

    service = ProductionAgentService(store, run_id)
    with pytest.raises(RequestError, match="focused-output review revision is in progress"):
        service.apply(
            _normal_apply_item_second_request(store, run_id),
            capability_token=grant_capability(store, run_id, role="producer", phase=PRODUCTION),
        )

    def _producer_defers() -> None:
        loop = store.load_review(run_id, loop_id)
        producer_session_id = str(
            primary_provider_session_id(store.load_run(run_id), "producer") or ""
        )
        token = grant_capability(
            store,
            run_id,
            role="producer",
            phase=PRODUCTION,
            session_id=producer_session_id,
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "target_revision": int(store.load_production(run_id)["output_revision"]),
                "target_digest": mandatory_output_digest(store, run_id),
                "finding_set_id": str(loop.get("finding_set_id") or ""),
                "finding_actions": [
                    {
                        "finding_id": "finding-opt",
                        "action": "defer",
                        "actor_role": "producer",
                        "rationale": "Accept risk for now.",
                    }
                ],
            },
            capability_token=token,
        )

    provider.script_turn(
        done_events(text="producer defer"),
        mutate_store=_producer_defers,
    )

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)

    assert result.ok is True
    assert result.status == "approved"
    assert store.load_review(run_id, loop_id)["status"] == "approved"
    assert focused_output_revision_transaction_active_loop(store, run_id) is None
    apply_production(
        store,
        run_id,
        _normal_apply_item_second_request(store, run_id),
        handler="apply",
    )()
    assert store.load_production(run_id)["dispositions"]["item-second"] == "completed"


def test_production_phase_rediscovers_review_incomplete_focused_output(
    tmp_path: Path,
) -> None:
    from top_down_planning.persistence.session_bindings import primary_provider_session_id

    from top_down_planning.orchestrator.provider_turns import (
        restore_primary_capability_after_focused_review,
    )

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000510-000510"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop = ReviewLoop.from_dict(_advisory_optional_focused_output_loop(item_ids=["item-first"]))
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())
    assert focused_output_revision_transaction_active_loop(store, run_id) is not None
    assert (
        find_resumable_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        == loop_id
    )

    def _producer_defers() -> None:
        loop_payload = store.load_review(run_id, loop_id)
        token = grant_capability(
            store,
            run_id,
            role="producer",
            phase=PRODUCTION,
            session_id=str(
                primary_provider_session_id(store.load_run(run_id), "producer") or ""
            ),
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "target_revision": int(store.load_production(run_id)["output_revision"]),
                "target_digest": mandatory_output_digest(store, run_id),
                "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
                "finding_actions": [
                    {
                        "finding_id": "finding-opt",
                        "action": "defer",
                        "actor_role": "producer",
                        "rationale": "Accept risk for now.",
                    }
                ],
            },
            capability_token=token,
        )

    provider.script_turn(
        done_events(text="producer defer after restart"),
        mutate_store=_producer_defers,
    )

    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    restore_primary_capability_after_focused_review(
        store,
        run_id,
        provider,
        review_type="focused_output",
        role="producer",
        current_token=token,
    )

    assert store.load_review(run_id, loop_id)["status"] == "approved"
    assert focused_output_revision_transaction_active_loop(store, run_id) is None
    apply_production(
        store,
        run_id,
        _normal_apply_item_second_request(store, run_id),
        handler="apply",
    )()
    assert store.load_production(run_id)["dispositions"]["item-second"] == "completed"


def test_run_pending_focused_review_repeated_review_incomplete_does_not_raise(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        FocusedReviewRunOutcome,
        run_pending_focused_review,
    )

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000512-000512"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop = ReviewLoop.from_dict(_advisory_optional_focused_output_loop(item_ids=["item-first"]))
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())
    assert (
        find_resumable_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        == loop_id
    )

    provider.script_turn(done_events(text="advisory retry without owner action"))

    outcome = run_pending_focused_review(
        store,
        run_id,
        provider,
        review_type="focused_output",
    )
    assert outcome == FocusedReviewRunOutcome.REVIEW_INCOMPLETE

    persisted = store.load_review(run_id, loop_id)
    assert persisted["status"] == "review_incomplete"
    run = store.load_run(run_id)
    assert run["status"] == "running"
    stop_code = str((run.get("stop") or {}).get("code") or "")
    assert stop_code != "review_state_conflict"


def test_production_phase_rediscovers_changes_requested_focused_output(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000511-000511"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    respond_review(
        store,
        run_id,
        review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            decision="changes_requested",
            target_revision=int(store.load_review(run_id, loop_id)["target_revision"]),
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-first"],
                    "issue": "Evidence is incomplete.",
                    "recommended_change": "Add a revised artifact.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=PRODUCTION,
        loop_id=loop_id,
    )()

    assert store.load_review(run_id, loop_id)["status"] == "changes_requested"
    assert (
        find_resumable_focused_review_loop_id(
            store,
            run_id,
            review_type="focused_output",
        )
        == loop_id
    )

    provider.script_turn(done_events(text="owner revision handoff"))
    FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)

    assert int(store.load_review(run_id, loop_id)["revision_cycles"]) >= 1


def test_focused_output_producer_advisory_handoff_uses_record_actions_boundary(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import ProviderTurnOutcome

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000505-000505"
    session_id = create_production_run_open_item_second(store, provider, run_id=run_id)
    save_review_payload(
        store,
        run_id,
        _advisory_optional_focused_output_loop(item_ids=["item-first"]),
    )
    loop_id = "review-focused-output-01"
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(ReviewLoop.from_dict(store.load_review(run_id, loop_id)))
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    calls: list[str] = []

    def _fake_finding_turn(*_args, **kwargs):
        calls.append(str(kwargs.get("loop_id")))
        return ProviderTurnOutcome(
            signal=None,
            session_id=session_id,
            replaced=False,
            domain_budget_committed=False,
        )

    with patch(
        "top_down_planning.orchestrator.review_loop_driver."
        "consume_owner_finding_action_turn_with_session_recovery",
        side_effect=_fake_finding_turn,
    ):
        driver._consume_owner_turn(
            session_id,
            PRODUCTION,
            loop_id=loop_id,
            handoff="advisory",
        )

    assert calls == [loop_id]
