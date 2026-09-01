"""Focused-review success, stale blockers, and producer-turn yield."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.domain.production_blockers import (
    BLOCKER_KIND_EXTERNAL,
    BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
    BLOCKER_STATUS_RESOLVED,
)
from top_down_planning.domain.reviews import ReviewLoop, is_terminal_review_loop
from top_down_planning.orchestrator.focused_review import FocusedReviewAdapter
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_production,
    done_events,
    grant_capability,
    request_focused_review,
    respond_review,
)
from tests.support.focused_review import create_production_run, review_respond_request


def test_focused_output_request_and_approval_does_not_use_blocker(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    provider.script_session_turn(
        producer_session_id,
        done_events(text="after review request"),
        mutate_store=request_focused_review(
            store,
            run_id,
            {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
            role="producer",
            phase=PRODUCTION,
        ),
    )
    provider.script_turn(
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            review_respond_request(
                store,
                run_id,
                loop_id="review-focused-output-01",
                decision="approved",
            ),
            phase=PRODUCTION,
            loop_id="review-focused-output-01",
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {
                "production_revision": 0,
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
                "empty_output": False,
            },
            handler="apply",
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {"goal_assessment": "Output goal is fully met."},
            handler="submit_completion",
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    production = store.load_production(run_id)
    report = production.get("blocker_report")
    assert report in (None, {}) or str(report.get("status") or "") == BLOCKER_STATUS_RESOLVED
    review = store.load_review(run_id, "review-focused-output-01")
    assert review["status"] == "approved"
    assert is_terminal_review_loop(ReviewLoop.from_dict(review)) is True
    events = store.load_events(run_id)
    assert any(event.get("type") == "focused_review_approved" for event in events)
    run = store.load_run(run_id)
    assert run["outcome"] != "blocked"


def test_legacy_review_bound_blocker_resolves_after_focused_approval(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"

    def _request_and_report_blocked() -> None:
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
                "evidence": "Waiting on focused review.",
                "affected_refs": ["item-first"],
                "summary": "focused review pending",
            },
            capability_token=token,
        )

    provider.script_session_turn(
        producer_session_id,
        done_events(text="request and wait"),
        mutate_store=_request_and_report_blocked,
    )
    provider.script_turn(
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            review_respond_request(
                store,
                run_id,
                loop_id="review-focused-output-01",
                decision="approved",
            ),
            phase=PRODUCTION,
            loop_id="review-focused-output-01",
        ),
    )

    def _apply_batch_after_blocker() -> None:
        apply_production(
            store,
            run_id,
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
                "empty_output": False,
            },
            handler="apply",
        )()

    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=_apply_batch_after_blocker,
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {"goal_assessment": "Output goal is fully met."},
            handler="submit_completion",
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    production = store.load_production(run_id)
    report = production.get("blocker_report") or {}
    assert report.get("kind") == BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    assert report.get("status") == BLOCKER_STATUS_RESOLVED
    run = store.load_run(run_id)
    assert run.get("outcome") != "blocked"


def test_external_blocker_still_terminals_production(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"

    def _report_external() -> None:
        token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
        ProductionAgentService(store, run_id).report_blocked(
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "evidence": "Vendor API is down.",
                "affected_refs": ["item-first"],
                "summary": "external outage",
                "kind": BLOCKER_KIND_EXTERNAL,
            },
            capability_token=token,
        )

    provider.script_session_turn(
        producer_session_id,
        done_events(text="blocked"),
        mutate_store=_report_external,
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "completed"
    assert run["outcome"] == "blocked"


def test_focused_success_commit_crash_does_not_emit_event_without_approved(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    create_production_run(store)
    run_id = "run-20260101T000501-000501"
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    loop = ReviewLoop.from_dict(store.load_review(run_id, "review-focused-output-01"))
    from dataclasses import replace

    verified = replace(loop, status="verified")
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(verified)

    with patch.object(store, "commit", side_effect=OSError("simulated crash")):
        with pytest.raises(OSError, match="simulated crash"):
            adapter.complete_success(verified)

    review = store.load_review(run_id, "review-focused-output-01")
    assert review["status"] != "approved"
    events = store.load_events(run_id)
    assert not any(event.get("type") == "focused_review_approved" for event in events)


def test_complete_success_reconciles_blocker_after_approved_event(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from top_down_planning.persistence.commit import CommitSpec

    store = FileRunStore(tmp_path)
    create_production_run(store)
    run_id = "run-20260101T000501-000501"
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
            "evidence": "Waiting on focused review.",
            "affected_refs": ["item-first"],
            "summary": "focused review pending",
        },
        capability_token=token,
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, "review-focused-output-01"))
    approved = replace(loop, status="approved")
    store.commit(
        run_id,
        CommitSpec(
            reviews=[approved.to_dict()],
            review_expected_revisions={approved.id: int(approved.revision)},
            events=[
                {
                    "type": "focused_review_approved",
                    "run_id": run_id,
                    "loop_id": approved.id,
                    "review_type": approved.type,
                    "target_revision": approved.target_revision,
                }
            ],
        ),
    )
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(approved)
    adapter.complete_success(approved)

    report = store.load_production(run_id).get("blocker_report") or {}
    assert report.get("status") == BLOCKER_STATUS_RESOLVED
    assert report.get("resolved_by") == approved.id


def test_active_review_wait_pauses_production(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-first"],
            "dispositions": {"item-first": {"disposition": "completed"}},
            "outputs": [],
            "contributions": [],
            "summary": "batch complete",
            "empty_output": False,
        },
        handler="apply",
    )()
    apply_production(
        store,
        run_id,
        {"goal_assessment": "Output goal is fully met."},
        handler="submit_completion",
    )()
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
        "status": "active",
        "review_loop_id": "review-focused-output-missing",
        "target_revision": 0,
        "evidence": "Waiting on focused review.",
        "affected_refs": ["item-first"],
        "summary": "focused review pending",
    }
    store.save_production(run_id, updated, expected)
    provider.script_session_turn(
        producer_session_id,
        done_events(text="producer session resume"),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()
    run = store.load_run(run_id)

    assert result.ok is False
    assert run["status"] == "paused"
    assert run["outcome"] is None
    assert run["stop"]["code"] == "focused_review_wait"


def test_production_continues_after_focused_review_wait_is_satisfied(
    tmp_path: Path,
) -> None:
    from tests.helpers import make_review_loop, save_review_payload

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-first"],
            "dispositions": {"item-first": {"disposition": "completed"}},
            "outputs": [],
            "contributions": [],
            "summary": "batch complete",
            "empty_output": False,
        },
        handler="apply",
    )()
    apply_production(
        store,
        run_id,
        {"goal_assessment": "Output goal is fully met."},
        handler="submit_completion",
    )()
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
        "status": "active",
        "review_loop_id": "review-focused-output-01",
        "target_revision": 0,
        "evidence": "Waiting on focused review.",
        "affected_refs": ["item-first"],
        "summary": "focused review pending",
    }
    store.save_production(run_id, updated, expected)
    provider.script_session_turn(
        producer_session_id,
        done_events(text="producer session resume"),
    )
    paused = ProductionPhaseOrchestrator(store, run_id, provider).run()
    assert paused.ok is False
    assert store.load_run(run_id)["stop"]["code"] == "focused_review_wait"

    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=0,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess-fr",
    )
    save_review_payload(store, run_id, loop.to_dict())
    run = store.load_run(run_id)
    expected_run = int(run["revision"])
    resumed = dict(run)
    resumed["revision"] = expected_run + 1
    resumed["status"] = "running"
    resumed["stop"] = None
    store.save_run(run_id, resumed, expected_run)
    provider.script_session_turn(
        producer_session_id,
        done_events(text="producer session resume after wait"),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()
    run = store.load_run(run_id)
    report = store.load_production(run_id).get("blocker_report") or {}

    assert result.ok is True
    assert run.get("status") != "paused"
    assert report.get("status") == BLOCKER_STATUS_RESOLVED


def test_in_progress_focused_review_is_resumed_during_production(tmp_path: Path) -> None:
    from tests.helpers import make_review_loop, save_review_payload

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=0,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="pending",
        reviewer_session_id="sess-fr",
    )
    save_review_payload(store, run_id, loop.to_dict())
    provider.script_session_turn(
        "sess-fr",
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            review_respond_request(
                store,
                run_id,
                loop_id=loop.id,
                decision="approved",
            ),
            phase=PRODUCTION,
            loop_id=loop.id,
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
                "empty_output": False,
            },
            handler="apply",
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {"goal_assessment": "Output goal is fully met."},
            handler="submit_completion",
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    review = store.load_review(run_id, loop.id)
    assert review["status"] == "approved"
    run = store.load_run(run_id)
    assert run.get("status") != "paused"
    assert run.get("outcome") != "blocked"
