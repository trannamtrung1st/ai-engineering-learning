"""Focused owner-revision restart when recheck transition was not persisted."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.agent_tool import ProductionAgentService, ReviewAgentService
from top_down_planning.domain.reviews import (
    ReviewLoop,
    focused_review_owner_revision_cycle_charged,
    focused_review_producer_owner_work_pending,
)
from top_down_planning.orchestrator.focused_review import (
    FocusedReviewAdapter,
    FocusedReviewOrchestrator,
)
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.provider_turns import owner_revision_complete
from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_plan,
    apply_plan_and_complete_focused_owner_revision,
    done_events,
    grant_capability,
    record_focused_owner_revision_complete,
    request_focused_review,
    respond_review,
    save_review_payload,
)
from tests.support.focused_review import (
    create_planning_run,
    create_production_run_open_item_second,
    focused_plan_request,
    review_respond_request,
)


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


def _normalize_focused_plan_loop(
    store: FileRunStore,
    run_id: str,
    provider: StubProvider,
    loop_id: str,
) -> tuple[ReviewLoop, bool]:
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    reviewer_session_id = reviewer_loop_provider_session_id(loop) or "reviewer-sess"
    provider.script_session_turn(
        reviewer_session_id,
        done_events(text="focused plan verification delivery"),
    )
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)
    return driver._normalize_loop_for_resume(loop)


def _inject_focused_owner_actions_before_artifact_advance(
    store: FileRunStore,
    run_id: str,
    loop_id: str,
    *,
    role: str,
    artifact_revision: int,
) -> None:
    """Persist owner actions without advancing artifact (crash-before-apply simulation)."""

    loop_payload = dict(store.load_review(run_id, loop_id))
    finding_set_id = str(loop_payload.get("finding_set_id") or "")
    cycle = max(int(loop_payload.get("revision_cycles") or 0), 1)
    loop_payload["finding_actions"] = [
        {
            "finding_id": "finding-01",
            "finding_set_id": finding_set_id,
            "action": "fix",
            "actor_role": role,
            "owner_revision_cycle": cycle,
            "artifact_revision": artifact_revision,
            "rationale": "Simulate crash before artifact revision advanced.",
        }
    ]
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = cycle
    save_review_payload(store, run_id, loop_payload)


def _inject_focused_owner_challenge_action(
    store: FileRunStore,
    run_id: str,
    loop_id: str,
    *,
    role: str,
    artifact_revision: int,
) -> None:
    loop_payload = dict(store.load_review(run_id, loop_id))
    finding_set_id = str(loop_payload.get("finding_set_id") or "")
    cycle = max(int(loop_payload.get("revision_cycles") or 0), 1)
    loop_payload["finding_actions"] = [
        {
            "finding_id": "finding-01",
            "finding_set_id": finding_set_id,
            "action": "challenge",
            "actor_role": role,
            "owner_revision_cycle": cycle,
            "artifact_revision": artifact_revision,
            "proposed_disposition": "invalid",
            "challenge_reason": "invalid",
            "rationale": "Dispute finding without artifact revision.",
        }
    ]
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = cycle
    save_review_payload(store, run_id, loop_payload)


def _seed_focused_plan_owner_complete_pre_recheck(
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
    target_revision_before = int(store.load_review(run_id, loop_id)["target_revision"])
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)
    apply_plan_and_complete_focused_owner_revision(
        store,
        run_id,
        base_revision=target_revision_before,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {"outcome": "REST API endpoints exist."},
            }
        ],
        phase=PLANNING,
        loop_id=loop_id,
    )()
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)
    return loop_id, target_revision_before


def _seed_focused_output_owner_complete_pre_recheck(
    store: FileRunStore,
    run_id: str,
    tmp_path: Path,
) -> tuple[str, int]:
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
            target_revision=int(store.load_production(run_id)["output_revision"]),
            findings=[_blocker_finding(target_refs=["item-first"])],
        ),
        phase=PRODUCTION,
        loop_id=loop_id,
    )()
    target_revision_before = int(store.load_review(run_id, loop_id)["target_revision"])
    output_revision_before = int(store.load_production(run_id)["output_revision"])
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)
    artifact = tmp_path / "first-v2.txt"
    artifact.write_text("revised", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    ProductionAgentService(store, run_id).apply(
        {
            "production_revision": output_revision_before,
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
                    "summary": "Owner revision.",
                }
            ],
            "summary": "Focused owner revision.",
        },
        capability_token=token,
    )
    record_focused_owner_revision_complete(
        store,
        run_id,
        loop_id=loop_id,
        phase=PRODUCTION,
        role="producer",
    )
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)
    return loop_id, target_revision_before


def test_focused_plan_normalize_owner_complete_commits_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000701-000701"
    create_planning_run(store, run_id)
    loop_id, target_revision_before = _seed_focused_plan_owner_complete_pre_recheck(
        store,
        run_id,
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert focused_review_owner_revision_cycle_charged(loop)
    assert owner_revision_complete(store, run_id, loop_id)
    assert not focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )

    reviewer_session_id = reviewer_loop_provider_session_id(loop) or "reviewer-sess"
    provider.script_session_turn(
        reviewer_session_id,
        done_events(text="focused plan verification delivery"),
    )

    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)
    normalized, reviewer_turn_delivered = driver._normalize_loop_for_resume(loop)

    assert reviewer_turn_delivered is True
    review = store.load_review(run_id, loop_id)
    assert review["active_stage"] == "finding_verification"
    assert int(review["target_revision"]) == target_revision_before + 1
    recheck_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "focused_review_recheck_requested"
        and event.get("loop_id") == loop_id
    ]
    assert len(recheck_events) == 1
    assert recheck_events[0]["prior_target_revision"] == target_revision_before
    assert normalized.active_stage == "finding_verification"


def test_focused_plan_restart_actions_before_artifact_skips_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000704-000704"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    plan_revision = int(store.load_plan(run_id)["revision"])
    _inject_focused_owner_actions_before_artifact_advance(
        store,
        run_id,
        loop_id,
        role="planner",
        artifact_revision=plan_revision,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert owner_revision_complete(store, run_id, loop_id)
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )
    assert int(store.load_plan_model(run_id).revision) == target_revision

    _, reviewer_turn_delivered = _normalize_focused_plan_loop(
        store,
        run_id,
        provider,
        loop_id,
    )

    assert reviewer_turn_delivered is False
    review = store.load_review(run_id, loop_id)
    assert review.get("active_stage") != "finding_verification"
    assert int(review["target_revision"]) == target_revision
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )


def test_focused_plan_restart_artifact_before_actions_then_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000705-000705"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    apply_plan(
        store,
        run_id,
        base_revision=target_revision,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {"outcome": "REST API endpoints exist."},
            }
        ],
        phase=PLANNING,
    )()
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert not owner_revision_complete(store, run_id, loop_id)
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )

    _, reviewer_turn_delivered = _normalize_focused_plan_loop(
        store,
        run_id,
        provider,
        loop_id,
    )
    assert reviewer_turn_delivered is False
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )

    record_focused_owner_revision_complete(
        store,
        run_id,
        loop_id=loop_id,
        phase=PLANNING,
        role="planner",
    )
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)

    normalized, reviewer_turn_delivered = _normalize_focused_plan_loop(
        store,
        run_id,
        provider,
        loop_id,
    )
    assert reviewer_turn_delivered is True
    review = store.load_review(run_id, loop_id)
    assert review["active_stage"] == "finding_verification"
    assert int(review["target_revision"]) == target_revision + 1
    assert normalized.active_stage == "finding_verification"


def test_focused_output_restart_actions_before_artifact_skips_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000706-000706"
    create_production_run_open_item_second(store, provider, run_id=run_id)
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
            target_revision=int(store.load_production(run_id)["output_revision"]),
            findings=[_blocker_finding(target_refs=["item-first"])],
        ),
        phase=PRODUCTION,
        loop_id=loop_id,
    )()
    target_revision = int(store.load_review(run_id, loop_id)["target_revision"])
    output_revision_before = int(store.load_production(run_id)["output_revision"])
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)
    output_revision_before = int(store.load_production(run_id)["output_revision"])
    _inject_focused_owner_actions_before_artifact_advance(
        store,
        run_id,
        loop_id,
        role="producer",
        artifact_revision=output_revision_before,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert owner_revision_complete(store, run_id, loop_id)
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_before

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    reviewer_session_id = reviewer_loop_provider_session_id(loop) or "reviewer-sess"
    provider.script_session_turn(
        reviewer_session_id,
        done_events(text="focused output verification delivery"),
    )
    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)
    _, reviewer_turn_delivered = driver._normalize_loop_for_resume(loop)

    assert reviewer_turn_delivered is False
    review = store.load_review(run_id, loop_id)
    assert review.get("active_stage") != "finding_verification"
    assert int(review["target_revision"]) == target_revision
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_before


def test_focused_producer_owner_work_pending_challenge_without_artifact_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000707-000707"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    plan_revision = int(store.load_plan(run_id)["revision"])
    _inject_focused_owner_challenge_action(
        store,
        run_id,
        loop_id,
        role="planner",
        artifact_revision=plan_revision,
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert int(store.load_plan_model(run_id).revision) == target_revision
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    ) is False


def test_focused_plan_orchestrator_actions_before_artifact_skips_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000708-000708"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    plan_revision = int(store.load_plan(run_id)["revision"])
    _inject_focused_owner_actions_before_artifact_advance(
        store,
        run_id,
        loop_id,
        role="planner",
        artifact_revision=plan_revision,
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
    assert int(store.load_plan_model(run_id).revision) == target_revision
    assert not any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )

    apply_plan(
        store,
        run_id,
        base_revision=target_revision,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {"outcome": "REST API endpoints exist."},
            }
        ],
        phase=PLANNING,
    )()
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["status"] = "pending"
    loop_payload["revision_cycles"] = max(int(loop_payload.get("revision_cycles") or 0), 1)
    save_review_payload(store, run_id, loop_payload)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    reviewer_session_id = reviewer_loop_provider_session_id(loop) or "reviewer-sess"
    provider.script_session_turn(
        reviewer_session_id,
        done_events(text="verification recheck delivery"),
    )
    normalized, reviewer_turn_delivered = _normalize_focused_plan_loop(
        store,
        run_id,
        provider,
        loop_id,
    )
    assert reviewer_turn_delivered is True
    assert normalized.active_stage == "finding_verification"
    review = store.load_review(run_id, loop_id)
    assert int(review["target_revision"]) == target_revision + 1
    assert any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )


def test_focused_plan_challenge_normalize_prepares_recheck_without_artifact(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000709-000709"
    create_planning_run(store, run_id)
    loop_id, target_revision = _charge_focused_plan_owner_cycle(store, run_id)
    plan_revision = int(store.load_plan(run_id)["revision"])
    _inject_focused_owner_challenge_action(
        store,
        run_id,
        loop_id,
        role="planner",
        artifact_revision=plan_revision,
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    ) is False

    normalized, reviewer_turn_delivered = _normalize_focused_plan_loop(
        store,
        run_id,
        provider,
        loop_id,
    )

    assert reviewer_turn_delivered is True
    review = store.load_review(run_id, loop_id)
    assert review["active_stage"] == "finding_verification"
    assert int(review["target_revision"]) == target_revision
    assert int(store.load_plan_model(run_id).revision) == target_revision
    assert any(
        event.get("type") == "focused_review_recheck_requested"
        for event in store.load_events(run_id)
    )
    assert normalized.active_stage == "finding_verification"


def test_focused_output_normalize_owner_complete_commits_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000702-000702"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop_id, target_revision_before = _seed_focused_output_owner_complete_pre_recheck(
        store,
        run_id,
        tmp_path,
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert owner_revision_complete(store, run_id, loop_id)
    assert not focused_review_producer_owner_work_pending(
        loop,
        store=store,
        run_id=run_id,
    )

    reviewer_session_id = reviewer_loop_provider_session_id(loop) or "reviewer-sess"
    provider.script_session_turn(
        reviewer_session_id,
        done_events(text="focused output verification delivery"),
    )

    adapter = FocusedReviewAdapter(store, run_id)
    adapter.bind_loop(loop)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)
    normalized, reviewer_turn_delivered = driver._normalize_loop_for_resume(loop)

    assert reviewer_turn_delivered is True
    review = store.load_review(run_id, loop_id)
    assert review["active_stage"] == "finding_verification"
    assert int(review["target_revision"]) == target_revision_before + 1
    recheck_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "focused_review_recheck_requested"
        and event.get("loop_id") == loop_id
    ]
    assert len(recheck_events) == 1
    assert recheck_events[0]["prior_target_revision"] == target_revision_before
    assert normalized.active_stage == "finding_verification"
