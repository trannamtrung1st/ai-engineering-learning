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
from top_down_planning.orchestrator.focused_review import (
    FocusedReviewAdapter,
    FocusedReviewOrchestrator,
)
from top_down_planning.orchestrator.reviewer_session import (
    reviewer_loop_provider_session_id,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_production,
    done_events,
    grant_capability,
    mandatory_output_digest,
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


def test_historical_untyped_blocker_does_not_terminalize_after_approved_review(
    tmp_path: Path,
) -> None:
    from tests.helpers import make_review_loop, save_review_payload
    from top_down_planning.persistence.commit import CommitSpec

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
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess-fr",
        verification_result={"target_digest": "digest-a", "decision": "verified"},
    )
    save_review_payload(store, run_id, loop.to_dict())
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    store.commit(
        run_id,
        CommitSpec(
            production=updated,
            production_expected_revision=expected,
            events=[
                {
                    "type": "focused_review_requested",
                    "run_id": run_id,
                    "loop_id": loop.id,
                    "review_type": "focused_output",
                    "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
                    "target_revision": 2,
                    "target_digest": "digest-a",
                },
                {
                    "type": "production_blocked_reported",
                    "run_id": run_id,
                    "affected_refs": ["item-first"],
                    "production_revision": updated["revision"],
                },
                {
                    "type": "focused_review_approved",
                    "run_id": run_id,
                    "loop_id": loop.id,
                    "review_type": "focused_output",
                    "target_revision": 2,
                },
            ],
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(text="producer session resume"),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()
    run = store.load_run(run_id)
    report = store.load_production(run_id).get("blocker_report") or {}

    assert result.ok is True
    assert run.get("outcome") != "blocked"
    assert report.get("kind") == BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    assert report.get("status") == BLOCKER_STATUS_RESOLVED
    assert report.get("resolved_by") == loop.id


def test_focused_review_requested_event_persists_target_digest(tmp_path: Path) -> None:
    from top_down_planning.persistence.digests import compute_output_digest

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
    expected = compute_output_digest(store.load_production(run_id))
    requested = next(
        event
        for event in store.load_events(run_id)
        if event.get("type") == "focused_review_requested"
    )
    assert requested.get("target_digest") == expected
    assert requested.get("target_revision") is not None


def test_completed_blocked_stale_review_wait_is_reopened_and_continues(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator import RunEngine
    from top_down_planning.orchestrator.run_transitions import complete_run_with_outcome
    from tests.helpers import make_review_loop, save_review_payload
    from top_down_planning.persistence.commit import CommitSpec

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
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess-fr",
        verification_result={"target_digest": "digest-a", "decision": "verified"},
    )
    save_review_payload(store, run_id, loop.to_dict())
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    store.commit(
        run_id,
        CommitSpec(
            production=updated,
            production_expected_revision=expected,
            events=[
                {
                    "type": "focused_review_requested",
                    "run_id": run_id,
                    "loop_id": loop.id,
                    "review_type": "focused_output",
                    "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
                    "target_revision": 2,
                    "target_digest": "digest-a",
                },
                {
                    "type": "production_blocked_reported",
                    "run_id": run_id,
                    "affected_refs": ["item-first"],
                    "production_revision": updated["revision"],
                },
                {
                    "type": "focused_review_approved",
                    "run_id": run_id,
                    "loop_id": loop.id,
                    "review_type": "focused_output",
                    "target_revision": 2,
                },
            ],
        ),
    )
    complete_run_with_outcome(
        store,
        run_id,
        "blocked",
        event_type="production_failed",
        message="Producer is waiting for focused review of item-first.",
    )
    run = store.load_run(run_id)
    assert run["status"] == "completed"
    assert run["outcome"] == "blocked"
    revision_before = int(run["revision"])

    provider.script_session_turn(
        producer_session_id,
        done_events(text="producer session resume after stale blocker repair"),
    )
    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
    ).continue_run(run_id, until="validated")

    run = store.load_run(run_id)
    report = store.load_production(run_id).get("blocker_report") or {}
    events = store.load_events(run_id)
    assert result.ok is True
    assert run.get("outcome") != "blocked"
    assert int(run["revision"]) > revision_before
    assert report.get("status") == BLOCKER_STATUS_RESOLVED
    assert report.get("resolved_by") == loop.id
    assert any(event.get("type") == "stale_blocked_run_reopened" for event in events)


def test_completed_blocked_run_is_not_reopened_after_later_deadlock(
    tmp_path: Path,
) -> None:
    from top_down_planning.domain.production_blockers import stale_blocked_run_is_repairable
    from top_down_planning.orchestrator import RunEngine
    from top_down_planning.orchestrator.run_transitions import complete_run_with_outcome
    from tests.helpers import make_review_loop, save_review_payload
    from top_down_planning.persistence.commit import CommitSpec

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess-fr",
        verification_result={"target_digest": "digest-a", "decision": "verified"},
    )
    save_review_payload(store, run_id, loop.to_dict())
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    store.commit(
        run_id,
        CommitSpec(
            production=updated,
            production_expected_revision=expected,
            events=[
                {
                    "type": "focused_review_requested",
                    "run_id": run_id,
                    "loop_id": loop.id,
                    "review_type": "focused_output",
                    "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
                    "target_revision": 2,
                    "target_digest": "digest-a",
                },
                {
                    "type": "production_blocked_reported",
                    "run_id": run_id,
                    "affected_refs": ["item-first"],
                    "production_revision": updated["revision"],
                },
                {
                    "type": "focused_review_approved",
                    "run_id": run_id,
                    "loop_id": loop.id,
                    "review_type": "focused_output",
                    "target_revision": 2,
                },
            ],
        ),
    )
    complete_run_with_outcome(
        store,
        run_id,
        "blocked",
        event_type="production_failed",
        message=(
            "All remaining applicable items are waiting and none are ready "
            "because dependency cycle: item-a -> item-b -> item-a"
        ),
        cause="deadlock",
    )
    run = store.load_run(run_id)
    revision_before = int(run["revision"])
    reviews = [ReviewLoop.from_dict(raw) for raw in store.list_reviews(run_id)]
    repair = stale_blocked_run_is_repairable(
        run=run,
        production=store.load_production(run_id),
        reviews=reviews,
        events=store.load_events(run_id),
    )
    assert repair is None

    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
    ).continue_run(run_id, until="validated")

    run = store.load_run(run_id)
    events = store.load_events(run_id)
    assert result.ok is False
    assert run["status"] == "completed"
    assert run["outcome"] == "blocked"
    assert int(run["revision"]) == revision_before
    assert not any(event.get("type") == "stale_blocked_run_reopened" for event in events)


def test_ordinary_completed_blocked_run_is_not_reopened(tmp_path: Path) -> None:
    from top_down_planning.orchestrator import RunEngine
    from top_down_planning.orchestrator.run_transitions import complete_run_with_outcome

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["blocker_report"] = {
        "kind": BLOCKER_KIND_EXTERNAL,
        "evidence": "Vendor API is down.",
        "affected_refs": ["item-first"],
        "summary": "external outage",
    }
    store.save_production(run_id, updated, expected)
    complete_run_with_outcome(store, run_id, "blocked")
    before = store.load_run(run_id)

    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
    ).continue_run(run_id, until="completed")

    after = store.load_run(run_id)
    assert result.ok is False
    assert after["status"] == "completed"
    assert after["outcome"] == "blocked"
    assert int(after["revision"]) == int(before["revision"])


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
    failed = next(
        event
        for event in store.load_events(run_id)
        if event.get("type") == "production_failed"
    )
    assert failed.get("cause") == "production_blocker"
    assert failed.get("blocker_kind") == BLOCKER_KIND_EXTERNAL
    assert failed.get("message") == "Vendor API is down."


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


def _complete_item_first(store: FileRunStore, run_id: str) -> None:
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-first"],
            "dispositions": {"item-first": {"disposition": "completed"}},
            "outputs": [
                {
                    "id": "output-first",
                    "type": "artifact",
                    "ref": "artifacts/first.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first"],
                    "summary": "Initial evidence.",
                }
            ],
            "summary": "batch complete",
        },
        handler="apply",
    )()


def test_focused_output_revision_recheck_supersedes_blocker_and_continues(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "first.txt").write_text("v1", encoding="utf-8")
    _complete_item_first(store, run_id)
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    loop_id = "review-focused-output-01"
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
    bound_before = store.load_production(run_id).get("blocker_report") or {}
    revision_a = int(bound_before.get("target_revision") or 0)
    digest_a = str(bound_before.get("target_digest") or "")
    assert revision_a > 0
    assert digest_a
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
    reviewer_session_id = reviewer_loop_provider_session_id(
        store.load_review(run_id, loop_id)
    )
    (artifacts / "first-v2.txt").write_text("v2", encoding="utf-8")
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
    revision_b = int(store.load_production(run_id)["output_revision"])
    digest_b = mandatory_output_digest(store, run_id)
    assert revision_b != revision_a
    assert digest_b != digest_a

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

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)
    events = store.load_events(run_id)
    recheck = next(
        event
        for event in events
        if event.get("type") == "focused_review_recheck_requested"
        and event.get("loop_id") == loop_id
    )
    review = store.load_review(run_id, loop_id)
    report = store.load_production(run_id).get("blocker_report") or {}

    assert result.ok is True
    assert review["status"] == "approved"
    assert int(review["target_revision"]) != revision_a
    assert recheck.get("prior_target_revision") == revision_a
    assert recheck.get("target_revision") == revision_b
    assert recheck.get("target_digest") == digest_b
    assert report.get("status") == BLOCKER_STATUS_RESOLVED
    assert report.get("target_revision") == revision_b
    assert report.get("target_digest") == digest_b
    assert not any(
        event.get("type") == "focused_review_requested"
        and event.get("loop_id") == loop_id
        and event.get("target_revision") == recheck.get("target_revision")
        for event in events
        if event.get("type") == "focused_review_requested"
    )

    provider.script_session_turn(
        producer_session_id,
        done_events(text="producer session resume after recheck"),
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
    production_result = ProductionPhaseOrchestrator(store, run_id, provider).run()
    run = store.load_run(run_id)
    assert production_result.ok is True
    assert run.get("outcome") != "blocked"


def test_focused_recheck_commit_crash_does_not_split_loop_and_event(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.focused_review import FocusedReviewAdapter
    from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
    from tests.support.persistence import _crash_before_appending_events, _find_txn_dir

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "first.txt").write_text("v1", encoding="utf-8")
    _complete_item_first(store, run_id)
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase=PRODUCTION,
    )()
    loop_id = "review-focused-output-01"
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
    (artifacts / "first-v2.txt").write_text("v2", encoding="utf-8")
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
    before = store.load_review(run_id, loop_id)
    events_before = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "focused_review_recheck_requested"
    ]
    adapter = FocusedReviewAdapter(store, run_id)
    loop = ReviewLoop.from_dict(before)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)

    with patch(
        "top_down_planning.persistence.file_store.atomic_write_json",
        _crash_before_appending_events(),
    ):
        with pytest.raises(OSError, match="simulated crash"):
            driver._prepare_recheck(loop)

    recovered = FileRunStore(tmp_path)
    after = recovered.load_review(run_id, loop_id)
    events_after = [
        event
        for event in recovered.load_events(run_id)
        if event.get("type") == "focused_review_recheck_requested"
    ]
    assert after["target_revision"] == before["target_revision"] or (
        after["target_revision"] != before["target_revision"] and events_after
    )
    if after["target_revision"] != before["target_revision"]:
        assert len(events_after) == len(events_before) + 1
        recheck = events_after[-1]
        assert recheck.get("loop_id") == loop_id
        assert recheck.get("prior_target_revision") == before["target_revision"]
        assert recheck.get("target_revision") == after["target_revision"]
    else:
        assert events_after == events_before
    assert _find_txn_dir(recovered, run_id) is None
