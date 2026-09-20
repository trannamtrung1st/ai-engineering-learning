"""Focused-output owner revision, evidence_revision, and blocker orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.domain.production_blockers import (
    BLOCKER_KIND_EXTERNAL,
    BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
    BLOCKER_STATUS_RESOLVED,
)
from top_down_planning.domain.reviews import (
    ReviewLoop,
    focused_output_evidence_revision_allowed,
    focused_output_revision_target_ids,
)
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.provider_turns import find_pending_focused_review_loop_id
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    done_events,
    grant_capability,
    request_focused_review,
    respond_review,
    review_loop_dict_with_binding,
    save_review_payload,
)
from tests.support.focused_review import create_production_run, review_respond_request
from tests.unit.test_focused_evidence_revision import (
    _create_run,
    _focused_review,
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


def test_evidence_revision_allowed_after_owner_actions_recorded_before_artifact(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import owner_revision_complete

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    _create_run(store)
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
        )

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
    _create_run(store)
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


def test_focused_evidence_revision_apply_after_owner_handoff(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000551-000551"
    _create_run(store)
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
    _create_run(store)
    fresh = _focused_review(item_ids=["item-first"], status="pending")
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
