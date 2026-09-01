"""Structured production blockers and stale review-bound reconciliation."""

from __future__ import annotations

from top_down_planning.domain.production_blockers import (
    BLOCKER_KIND_EXTERNAL,
    BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
    BLOCKER_STATUS_ACTIVE,
    BLOCKER_STATUS_RESOLVED,
    bind_open_focused_review_to_blocker,
    evaluate_blocker_report,
    normalize_blocker_report,
    review_satisfies_blocker,
    resolve_blocker_report,
    stale_blocked_run_is_repairable,
)
from top_down_planning.domain.reviews import (
    is_terminal_review_loop,
    normalize_focused_review_success,
)
from tests.helpers import make_review_loop


def _approved_focused_loop(
    *,
    loop_id: str = "review-focused-output-01",
    target_revision: int = 2,
    target_digest: str = "digest-a",
) -> ReviewLoop:
    return make_review_loop(
        id=loop_id,
        type="focused_output",
        target_revision=target_revision,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess",
        verification_result={
            "target_digest": target_digest,
            "decision": "verified",
        },
    )


def _review_bound_blocker(
    *,
    loop_id: str = "review-focused-output-01",
    target_revision: int = 2,
    target_digest: str = "digest-a",
    status: str = BLOCKER_STATUS_ACTIVE,
) -> dict[str, object]:
    return {
        "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
        "status": status,
        "review_loop_id": loop_id,
        "target_revision": target_revision,
        "target_digest": target_digest,
        "evidence": "Waiting on focused review.",
        "affected_refs": ["item-first"],
        "summary": "focused review pending",
        "plan_revision": 0,
        "output_revision": 2,
        "reported_at_output_revision": 2,
    }


def test_legacy_blocker_without_kind_is_active_external() -> None:
    report = normalize_blocker_report(
        {
            "evidence": "Upstream service unavailable.",
            "affected_refs": ["item-deploy"],
            "summary": "credentials",
            "plan_revision": 1,
            "output_revision": 3,
        }
    )
    assert report is not None
    assert report["kind"] == BLOCKER_KIND_EXTERNAL
    assert report["status"] == BLOCKER_STATUS_ACTIVE


def test_legacy_blocker_with_review_loop_id_is_review_wait() -> None:
    report = normalize_blocker_report(
        {
            "evidence": "Waiting on focused review.",
            "affected_refs": ["item-first"],
            "review_loop_id": "review-focused-output-01",
            "target_revision": 2,
            "target_digest": "digest-a",
            "output_revision": 2,
        }
    )
    assert report is not None
    assert report["kind"] == BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    assert report["status"] == BLOCKER_STATUS_ACTIVE


def test_same_loop_revision_and_digest_resolves_review_bound_blocker() -> None:
    report = _review_bound_blocker()
    loop = _approved_focused_loop()
    assert review_satisfies_blocker(report, loop) is True
    evaluation = evaluate_blocker_report(report, [loop])
    assert evaluation.disposition == "resolved"
    assert evaluation.matching_loop_id == loop.id
    resolved = resolve_blocker_report(report, resolved_by=loop.id)
    assert resolved["status"] == BLOCKER_STATUS_RESOLVED
    assert resolved["resolved_by"] == loop.id


def test_wrong_loop_does_not_resolve_review_bound_blocker() -> None:
    report = _review_bound_blocker(loop_id="review-focused-output-01")
    other = _approved_focused_loop(loop_id="review-focused-output-02")
    assert review_satisfies_blocker(report, other) is False
    evaluation = evaluate_blocker_report(report, [other])
    assert evaluation.disposition == "active_wait"


def test_wrong_revision_does_not_resolve_review_bound_blocker() -> None:
    report = _review_bound_blocker(target_revision=2)
    loop = _approved_focused_loop(target_revision=3)
    assert review_satisfies_blocker(report, loop) is False
    evaluation = evaluate_blocker_report(report, [loop])
    assert evaluation.disposition == "active_wait"


def test_wrong_digest_does_not_resolve_review_bound_blocker() -> None:
    report = _review_bound_blocker(target_digest="digest-a")
    loop = _approved_focused_loop(target_digest="digest-b")
    assert review_satisfies_blocker(report, loop) is False
    evaluation = evaluate_blocker_report(report, [loop])
    assert evaluation.disposition == "active_wait"


def test_blocked_focused_review_does_not_satisfy_review_bound_blocker() -> None:
    report = _review_bound_blocker()
    blocked = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="blocked",
        reviewer_session_id="sess",
        verification_result={
            "target_digest": "digest-a",
            "decision": "blocked",
        },
    )
    assert is_terminal_review_loop(blocked) is True
    assert review_satisfies_blocker(report, blocked) is False
    evaluation = evaluate_blocker_report(report, [blocked])
    assert evaluation.disposition == "active_wait"


def test_focused_review_wait_without_loop_id_is_not_terminal() -> None:
    report = normalize_blocker_report(
        {
            "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
            "status": BLOCKER_STATUS_ACTIVE,
            "evidence": "Waiting on focused review.",
            "affected_refs": ["item-first"],
        }
    )
    evaluation = evaluate_blocker_report(report, [])
    assert evaluation.disposition == "active_wait"


def test_approved_loop_without_digest_does_not_satisfy_digest_bound_blocker() -> None:
    report = _review_bound_blocker(target_digest="digest-a")
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess",
    )
    assert review_satisfies_blocker(report, loop) is False
    evaluation = evaluate_blocker_report(report, [loop])
    assert evaluation.disposition == "active_wait"


def test_untyped_blocker_is_not_bound_to_single_open_focused_loop() -> None:
    pending = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="pending",
        reviewer_session_id="sess",
    )
    bound = bind_open_focused_review_to_blocker(
        {
            "evidence": "Vendor API is down.",
            "affected_refs": ["item-first"],
            "summary": "external outage",
        },
        [pending],
        output_revision=2,
        output_digest="digest-a",
    )
    assert bound.get("kind") != BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    assert "review_loop_id" not in bound


def test_untyped_legacy_external_blocker_stays_terminal_while_focused_review_open() -> None:
    pending = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="pending",
        reviewer_session_id="sess",
    )
    report = {
        "evidence": "Vendor API is down.",
        "affected_refs": ["item-first"],
        "summary": "external outage",
        "plan_revision": 3,
        "output_revision": 12,
    }
    bound = bind_open_focused_review_to_blocker(
        report,
        [pending],
        output_revision=12,
    )
    evaluation = evaluate_blocker_report(
        bound,
        [pending],
        events=[
            {
                "type": "focused_review_requested",
                "loop_id": pending.id,
                "review_type": "focused_output",
                "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
                "target_revision": 2,
            },
            {
                "type": "production_blocked_reported",
                "affected_refs": ["item-first"],
            },
        ],
    )
    assert evaluation.disposition == "active_terminal"
    assert evaluation.report is not None
    assert evaluation.report["kind"] == BLOCKER_KIND_EXTERNAL
    assert evaluation.diagnostic_code == "ambiguous_legacy_blocker"


def test_legacy_untyped_blocker_not_resolved_when_review_completed_before_blocker() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = [
        {
            "type": "focused_review_requested",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
            "target_digest": "digest-a",
        },
        {
            "type": "focused_review_approved",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "target_revision": 2,
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
    ]
    evaluation = evaluate_blocker_report(report, [loop], events=events)
    assert evaluation.disposition == "active_terminal"
    assert evaluation.report is not None
    assert evaluation.report.get("status") != BLOCKER_STATUS_RESOLVED
    assert evaluation.matching_loop_id != loop.id or evaluation.disposition != "resolved"


def test_legacy_untyped_blocker_resolves_when_history_proves_satisfied_review_wait() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = [
        {
            "type": "focused_review_requested",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
            "target_digest": "digest-a",
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
        {
            "type": "focused_review_approved",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "target_revision": 2,
        },
    ]
    evaluation = evaluate_blocker_report(report, [loop], events=events)
    assert evaluation.disposition == "resolved"
    assert evaluation.matching_loop_id == loop.id
    assert evaluation.report is not None
    assert evaluation.report["kind"] == BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    assert evaluation.report["status"] == BLOCKER_STATUS_RESOLVED
    assert evaluation.report["resolved_by"] == loop.id
    assert evaluation.report["target_revision"] == 2
    assert evaluation.report["target_digest"] == "digest-a"


def test_review_wait_is_artifact_identity_from_request_not_final_loop() -> None:
    loop = _approved_focused_loop(target_revision=3, target_digest="digest-b")
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = [
        {
            "type": "focused_review_requested",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
            "target_digest": "digest-a",
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
        {
            "type": "focused_review_approved",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "target_revision": 3,
        },
    ]
    evaluation = evaluate_blocker_report(report, [loop], events=events)
    assert evaluation.disposition != "resolved"
    assert evaluation.report is None or evaluation.report.get("status") != BLOCKER_STATUS_RESOLVED


def test_later_request_on_same_loop_supersedes_artifact_wait_then_approval_resolves() -> None:
    loop = _approved_focused_loop(target_revision=3, target_digest="digest-b")
    report = _review_bound_blocker(target_revision=2, target_digest="digest-a")
    events = [
        {
            "type": "focused_review_requested",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
            "target_digest": "digest-a",
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
        {
            "type": "focused_review_requested",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 3,
            "target_digest": "digest-b",
        },
        {
            "type": "focused_review_approved",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "target_revision": 3,
        },
    ]
    evaluation = evaluate_blocker_report(report, [loop], events=events)
    assert evaluation.disposition == "resolved"
    assert evaluation.report is not None
    assert evaluation.report["target_revision"] == 3
    assert evaluation.report["target_digest"] == "digest-b"


def test_revision_cycle_without_new_request_does_not_satisfy_artifact_wait() -> None:
    loop = _approved_focused_loop(target_revision=3, target_digest="digest-b")
    report = _review_bound_blocker(target_revision=2, target_digest="digest-a")
    events = [
        {
            "type": "focused_review_requested",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
            "target_digest": "digest-a",
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
        {
            "type": "focused_review_approved",
            "loop_id": loop.id,
            "review_type": "focused_output",
            "target_revision": 3,
        },
    ]
    evaluation = evaluate_blocker_report(report, [loop], events=events)
    assert evaluation.disposition == "active_wait"
    assert review_satisfies_blocker(report, loop) is False


def _completed_blocked_run() -> dict[str, object]:
    return {"status": "completed", "outcome": "blocked", "phase": "production"}


def _stale_review_wait_chain(
    loop_id: str,
    *,
    target_revision: int = 2,
    target_digest: str = "digest-a",
    terminal: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    evidence = "Producer is waiting for focused review of item-first."
    events: list[dict[str, object]] = [
        {
            "type": "focused_review_requested",
            "loop_id": loop_id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": target_revision,
            "target_digest": target_digest,
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
        {
            "type": "focused_review_approved",
            "loop_id": loop_id,
            "review_type": "focused_output",
            "target_revision": target_revision,
        },
    ]
    if terminal is None:
        events.append(
            {
                "type": "production_failed",
                "outcome": "blocked",
                "message": evidence,
            }
        )
    else:
        events.append(terminal)
    return events


def test_stale_blocked_run_is_repairable_when_terminal_matches_blocker_evidence() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = _stale_review_wait_chain(loop.id)
    repair = stale_blocked_run_is_repairable(
        run=_completed_blocked_run(),
        production={"blocker_report": report},
        reviews=[loop],
        events=events,
    )
    assert repair is not None
    assert repair.disposition == "resolved"


def test_stale_blocked_run_is_repairable_with_explicit_blocker_cause() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = _stale_review_wait_chain(
        loop.id,
        terminal={
            "type": "production_failed",
            "outcome": "blocked",
            "message": "unrelated wording",
            "cause": "production_blocker",
            "blocker_kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
            "review_loop_id": loop.id,
            "target_revision": 2,
            "target_digest": "digest-a",
        },
    )
    repair = stale_blocked_run_is_repairable(
        run=_completed_blocked_run(),
        production={"blocker_report": report},
        reviews=[loop],
        events=events,
    )
    assert repair is not None


def test_stale_blocked_run_not_repairable_when_later_terminal_is_deadlock() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = _stale_review_wait_chain(
        loop.id,
        terminal={
            "type": "production_failed",
            "outcome": "blocked",
            "message": (
                "All remaining applicable items are waiting and none are ready "
                "because dependency cycle: item-a -> item-b -> item-a"
            ),
            "cause": "deadlock",
        },
    )
    assert evaluate_blocker_report(report, [loop], events=events).disposition == "resolved"
    repair = stale_blocked_run_is_repairable(
        run=_completed_blocked_run(),
        production={"blocker_report": report},
        reviews=[loop],
        events=events,
    )
    assert repair is None


def test_stale_blocked_run_not_repairable_when_legacy_deadlock_message_mismatches_blocker() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = _stale_review_wait_chain(
        loop.id,
        terminal={
            "type": "production_failed",
            "outcome": "blocked",
            "message": (
                "All remaining applicable items are waiting and none are ready "
                "because a required dependency has a blocked disposition"
            ),
        },
    )
    assert evaluate_blocker_report(report, [loop], events=events).disposition == "resolved"
    repair = stale_blocked_run_is_repairable(
        run=_completed_blocked_run(),
        production={"blocker_report": report},
        reviews=[loop],
        events=events,
    )
    assert repair is None


def test_stale_blocked_run_not_repairable_when_later_blocker_supersedes_chain() -> None:
    loop = _approved_focused_loop()
    report = {
        "evidence": "Producer is waiting for focused review of item-first.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = _stale_review_wait_chain(loop.id)
    events.append(
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        }
    )
    events.append(
        {
            "type": "production_failed",
            "outcome": "blocked",
            "message": "Producer is waiting for focused review of item-first.",
        }
    )
    repair = stale_blocked_run_is_repairable(
        run=_completed_blocked_run(),
        production={"blocker_report": report},
        reviews=[loop],
        events=events,
    )
    assert repair is None


def test_legacy_untyped_blocker_is_not_auto_cleared_when_history_is_ambiguous() -> None:
    first = _approved_focused_loop(loop_id="review-focused-output-01")
    second = _approved_focused_loop(loop_id="review-focused-output-02")
    report = {
        "evidence": "Producer is waiting for focused review.",
        "affected_refs": ["item-first"],
        "summary": "waiting for focused review",
        "plan_revision": 3,
        "output_revision": 12,
    }
    events = [
        {
            "type": "focused_review_requested",
            "loop_id": first.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
        },
        {
            "type": "focused_review_requested",
            "loop_id": second.id,
            "review_type": "focused_output",
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "target_revision": 2,
        },
        {
            "type": "production_blocked_reported",
            "affected_refs": ["item-first"],
        },
    ]
    evaluation = evaluate_blocker_report(report, [first, second], events=events)
    assert evaluation.disposition == "active_terminal"
    assert evaluation.diagnostic_code == "ambiguous_legacy_blocker"
    assert evaluation.report is not None
    assert evaluation.report.get("status") != BLOCKER_STATUS_RESOLVED


def test_explicit_focused_review_wait_binds_to_named_or_unique_open_loop() -> None:
    pending = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="pending",
        reviewer_session_id="sess",
    )
    bound = bind_open_focused_review_to_blocker(
        {
            "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
            "evidence": "Waiting on focused review.",
            "affected_refs": ["item-first"],
            "summary": "focused review pending",
        },
        [pending],
        output_revision=2,
        output_digest="digest-a",
    )
    assert bound["kind"] == BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    assert bound["review_loop_id"] == pending.id
    assert bound["target_revision"] == 2
    assert bound["target_digest"] == "digest-a"


def test_bind_skips_explicit_external_blocker() -> None:
    pending = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="pending",
        reviewer_session_id="sess",
    )
    bound = bind_open_focused_review_to_blocker(
        {
            "kind": BLOCKER_KIND_EXTERNAL,
            "evidence": "Vendor API is down.",
            "affected_refs": ["item-first"],
        },
        [pending],
        output_revision=2,
    )
    assert bound["kind"] == BLOCKER_KIND_EXTERNAL
    assert "review_loop_id" not in bound


def test_external_blocker_survives_unrelated_focused_review_approval() -> None:
    report = normalize_blocker_report(
        {
            "kind": BLOCKER_KIND_EXTERNAL,
            "evidence": "Vendor API is down.",
            "affected_refs": ["item-first"],
            "output_revision": 2,
        }
    )
    loop = _approved_focused_loop()
    evaluation = evaluate_blocker_report(report, [loop])
    assert evaluation.disposition == "active_terminal"


def test_resolved_blocker_is_not_active() -> None:
    report = _review_bound_blocker(status=BLOCKER_STATUS_RESOLVED)
    evaluation = evaluate_blocker_report(report, [_approved_focused_loop()])
    assert evaluation.disposition == "none"


def test_verified_focused_review_is_normalized_to_approved_terminal() -> None:
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        target_revision=1,
        scope={"kind": "focused_plan", "item_ids": ["item-api"]},
        status="verified",
        reviewer_session_id="sess",
    )
    assert is_terminal_review_loop(loop) is False
    normalized = normalize_focused_review_success(loop)
    assert normalized.status == "approved"
    assert is_terminal_review_loop(normalized) is True


def test_already_approved_focused_review_stays_approved() -> None:
    loop = _approved_focused_loop()
    normalized = normalize_focused_review_success(loop)
    assert normalized.status == "approved"
    assert is_terminal_review_loop(normalized) is True
