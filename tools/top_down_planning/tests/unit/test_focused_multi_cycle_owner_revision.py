"""Focused review owner-revision semantics across multiple revision cycles."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.agent_tool import ReviewAgentService
from top_down_planning.domain.reviews import (
    ReviewLoop,
    focused_review_producer_owner_work_pending,
    owner_actions_require_revision,
    effective_owner_actions,
    verification_required_for_loop,
)
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.orchestrator.focused_review import (
    FocusedReviewAdapter,
    FocusedReviewOrchestrator,
)
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_plan,
    done_events,
    grant_capability,
    respond_review,
    save_review_payload,
)
from tests.support.focused_review import create_planning_run, focused_plan_request, review_respond_request


def _blocker_finding(*, target_refs: list[str]) -> dict:
    return {
        "id": "finding-01",
        "severity": "blocker",
        "category": "correctness",
        "target_refs": target_refs,
        "issue": "Gap.",
        "recommended_change": "Fix.",
    }


def _charge_focused_plan_owner_cycle(
    store: FileRunStore,
    run_id: str,
) -> tuple[str, int]:
    created = ReviewAgentService(store, run_id).request(
        focused_plan_request(["item-api"], store, run_id=run_id),
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    loop_id = str(created["loop_id"])
    respond_review(
        store,
        run_id,
        review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            decision="changes_requested",
            findings=[_blocker_finding(target_refs=["item-api"])],
        ),
        phase=PLANNING,
        loop_id=loop_id,
    )()
    target_revision = int(store.load_review(run_id, loop_id)["target_revision"])
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)
    return loop_id, target_revision


def _enter_focused_owner_cycle(
    store: FileRunStore,
    run_id: str,
    loop_id: str,
    revision_cycles: int,
) -> ReviewLoop:
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    entered = adapter.enter_revision_cycle(loop, revision_cycles)
    save_review_payload(store, run_id, entered.to_dict())
    return ReviewLoop.from_dict(store.load_review(run_id, loop_id))


def _append_owner_action(
    store: FileRunStore,
    run_id: str,
    loop_id: str,
    *,
    action: str,
    owner_revision_cycle: int,
    artifact_revision: int,
    proposed_disposition: str | None = None,
    challenge_reason: str | None = None,
) -> None:
    loop_payload = dict(store.load_review(run_id, loop_id))
    finding_set_id = str(loop_payload.get("finding_set_id") or "")
    entry: dict = {
        "finding_id": "finding-01",
        "finding_set_id": finding_set_id,
        "action": action,
        "actor_role": "planner",
        "owner_revision_cycle": owner_revision_cycle,
        "artifact_revision": artifact_revision,
        "rationale": f"Owner action for cycle {owner_revision_cycle}.",
    }
    if proposed_disposition is not None:
        entry["proposed_disposition"] = proposed_disposition
    if challenge_reason is not None:
        entry["challenge_reason"] = challenge_reason
    existing = list(loop_payload.get("finding_actions") or [])
    existing.append(entry)
    loop_payload["finding_actions"] = existing
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)


def test_focused_enter_revision_cycle_clears_finding_verification_stage(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000801-000801"
    create_planning_run(store, run_id)
    loop_id, _target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["active_stage"] = "finding_verification"
    save_review_payload(store, run_id, loop_payload)

    entered = _enter_focused_owner_cycle(store, run_id, loop_id, revision_cycles=2)

    assert entered.revision_cycles == 2
    assert entered.active_stage is None


def test_cycle2_restart_before_owner_work_resumes_owner_not_reviewer(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000802-000802"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    _enter_focused_owner_cycle(store, run_id, loop_id, revision_cycles=2)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert loop.active_stage is None
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )

    provider.script_turn(done_events(text="planner primary session start"))
    provider.script_turn(done_events(text="owner revision session start"))
    provider.script_turn(done_events(text="owner revision turn"))

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)

    assert result.ok is False
    assert "owner revision" in (result.reason or "").lower()
    review = store.load_review(run_id, loop_id)
    assert review.get("active_stage") != "finding_verification"
    assert int(review["target_revision"]) == target_revision
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        and event.get("loop_id") == loop_id
        for event in store.load_events(run_id)
    )


def test_cycle2_stale_verification_stage_still_blocks_premature_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000803-000803"
    create_planning_run(store, run_id)
    loop_id, _target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["revision_cycles"] = 2
    loop_payload["active_stage"] = "finding_verification"
    loop_payload["status"] = "pending"
    save_review_payload(store, run_id, loop_payload)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )

    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)
    _, reviewer_turn_delivered = driver._normalize_loop_for_resume(loop)

    assert reviewer_turn_delivered is False
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )


def test_cycle2_fix_without_artifact_advance_blocks_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000804-000804"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    plan_revision = int(store.load_plan(run_id)["revision"])
    _append_owner_action(
        store,
        run_id,
        loop_id,
        action="fix",
        owner_revision_cycle=1,
        artifact_revision=plan_revision + 1,
    )
    _enter_focused_owner_cycle(store, run_id, loop_id, revision_cycles=2)
    _append_owner_action(
        store,
        run_id,
        loop_id,
        action="fix",
        owner_revision_cycle=2,
        artifact_revision=plan_revision,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert int(store.load_plan_model(run_id).revision) == plan_revision
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )


def test_cycle2_challenge_does_not_require_cycle1_fix_artifact(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000805-000805"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    plan_revision = int(store.load_plan(run_id)["revision"])
    _append_owner_action(
        store,
        run_id,
        loop_id,
        action="fix",
        owner_revision_cycle=1,
        artifact_revision=plan_revision + 1,
    )
    _enter_focused_owner_cycle(store, run_id, loop_id, revision_cycles=2)
    _append_owner_action(
        store,
        run_id,
        loop_id,
        action="challenge",
        owner_revision_cycle=2,
        artifact_revision=plan_revision,
        proposed_disposition="invalid",
        challenge_reason="invalid",
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    current_actions = list(
        effective_owner_actions(
            loop.finding_actions,
            finding_set_id=loop.finding_set_id,
            owner_revision_cycle=2,
        ).values()
    )
    assert owner_actions_require_revision(current_actions) is False
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    ) is False


def _optional_finding(*, target_refs: list[str]) -> dict:
    return {
        "id": "finding-opt",
        "severity": "minor",
        "category": "correctness",
        "target_refs": target_refs,
        "issue": "Optional polish.",
        "recommended_change": "Improve wording.",
        "status": "unresolved",
    }


def test_focused_optional_defer_after_charged_cycle_skips_recheck_and_completes(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000806-000806"
    create_planning_run(store, run_id)
    created = ReviewAgentService(store, run_id).request(
        focused_plan_request(["item-api"], store, run_id=run_id),
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    loop_id = str(created["loop_id"])
    respond_review(
        store,
        run_id,
        review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            decision="changes_requested",
            findings=[_optional_finding(target_refs=["item-api"])],
        ),
        phase=PLANNING,
        loop_id=loop_id,
    )()
    _enter_focused_owner_cycle(store, run_id, loop_id, revision_cycles=1)

    loop_payload = store.load_review(run_id, loop_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    ReviewAgentService(store, run_id).record_finding_actions(
        {
            "loop_id": loop_id,
            "target_revision": int(store.load_plan_model(run_id).revision),
            "target_digest": compute_plan_digest(store.load_plan_model(run_id)),
            "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
            "finding_actions": [
                {
                    "finding_id": "finding-opt",
                    "action": "defer",
                    "actor_role": "planner",
                    "rationale": "Accept optional risk for now.",
                }
            ],
        },
        capability_token=token,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert loop.status == "approved"
    assert verification_required_for_loop(loop) is False
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)
    assert driver._owner_work_complete_for_recheck(loop) is False

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop_id)

    assert result.ok is True
    assert store.load_review(run_id, loop_id)["status"] == "approved"
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )
