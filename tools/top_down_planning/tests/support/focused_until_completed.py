"""Stub-driven focused-output workflow through ``--until completed``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.provider import StubProvider
from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_plan_and_complete_focused_owner_revision,
    apply_production,
    done_events,
    grant_capability,
    mandatory_initial_respond_request,
    mandatory_output_digest,
    mandatory_plan_digest,
    mandatory_scope_review_respond_request,
    prepare_loop_for_scope_review_respond,
    record_finding_actions,
    respond_review,
    save_review_payload,
    with_root_contract,
)
from tests.support.focused_review import (
    create_planning_run,
    create_production_run_open_item_second,
    focused_owner_revision_pending_loop,
)
from tests.support.stub_provider_factory import RotatingStubProviderFactory


def seed_focused_output_owner_pending_after_evidence(
    store: FileRunStore,
    provider: StubProvider,
    *,
    run_id: str,
    record_owner_finding_actions: bool = True,
) -> str:
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop_id = "review-focused-output-01"
    save_review_payload(
        store,
        run_id,
        focused_owner_revision_pending_loop(item_ids=["item-first"]),
    )
    run = store.load_run(run_id)
    workspace = Path(str(run["workspace"]))
    artifact = workspace / "artifacts" / "first-v2.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("revised", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)
    production_revision = int(store.load_production(run_id)["revision"])
    result = service.apply(
        {
            "production_revision": production_revision,
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
                    "summary": "Evidence before owner actions.",
                }
            ],
            "summary": "Focused evidence revision first.",
        },
        capability_token=token,
    )
    assert result["ok"] is True
    if record_owner_finding_actions:
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
                        "rationale": "Evidence revision completed.",
                    }
                ],
            },
            role="producer",
            phase=PRODUCTION,
            loop_id=loop_id,
        )()
    return loop_id


def script_focused_output_through_completion(
    factory: RotatingStubProviderFactory,
    store: FileRunStore,
    run_id: str,
    loop_id: str,
) -> None:
    """Queue provider turns that complete owner work, recheck, production, and whole-output review."""

    loop_snapshot = store.load_review(run_id, loop_id)
    state = {
        "finding_actions": bool(loop_snapshot.get("finding_actions")),
        "verified": False,
        "item_second": False,
        "whole_output": False,
    }

    def _record_owner_actions() -> None:
        if state["finding_actions"]:
            return
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
                        "rationale": "Evidence revision completed.",
                    }
                ],
            },
            role="producer",
            phase=PRODUCTION,
            loop_id=loop_id,
        )()
        state["finding_actions"] = True

    def _verify_focused_review() -> None:
        if state["verified"]:
            return
        loop = store.load_review(run_id, loop_id)
        if str(loop.get("status") or "") == "approved":
            state["verified"] = True
            return
        if not state["finding_actions"]:
            return
        if str(loop.get("active_stage") or "") != "finding_verification":
            return
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
        state["verified"] = True

    def _complete_item_second() -> None:
        if state["item_second"]:
            return
        loop_payload = store.load_review(run_id, loop_id)
        if str(loop_payload.get("status") or "") != "approved":
            return
        apply_production(
            store,
            run_id,
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "plan_items": ["item-second"],
                "dispositions": {
                    "item-second": {
                        "disposition": "completed",
                        "evidence": "Second item complete.",
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
                        "summary": "Second item batch.",
                    }
                ],
                "summary": "Complete item-second.",
            },
            handler="apply",
        )()
        apply_production(
            store,
            run_id,
            {"goal_assessment": "Output goal is fully met."},
            handler="submit_completion",
        )()
        state["item_second"] = True

    whole_output_loop_id = "review-whole-output-01"

    def _whole_output_initial_respond() -> None:
        if state["whole_output"]:
            return
        run = store.load_run(run_id)
        if str(run.get("phase") or "") != WHOLE_OUTPUT_REVIEW:
            return
        loop_payload = store.load_review(run_id, whole_output_loop_id)
        target_revision = int(loop_payload["target_revision"])
        respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=whole_output_loop_id,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=whole_output_loop_id,
        )()
        prepare_loop_for_scope_review_respond(
            store,
            run_id,
            whole_output_loop_id,
            target_revision=target_revision,
        )

    def _whole_output_scope_respond() -> None:
        if state["whole_output"]:
            return
        run = store.load_run(run_id)
        if str(run.get("phase") or "") != WHOLE_OUTPUT_REVIEW:
            return
        loop_payload = store.load_review(run_id, whole_output_loop_id)
        target_revision = int(loop_payload["target_revision"])
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=whole_output_loop_id,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=whole_output_loop_id,
        )()
        state["whole_output"] = True

    factory.script_turn(done_events(text="production primary resume"))
    factory.script_turn(done_events(text="owner session rotate"))
    factory.script_turn(
        done_events(text="producer owner revision turn"),
        mutate_store=_record_owner_actions,
    )
    factory.script_turn(done_events(text="recheck delivery without respond"))
    factory.script_turn(
        done_events(text="reviewer verify"),
        mutate_store=_verify_focused_review,
    )
    whole_output_gate_state = {"initial": False}

    def _whole_output_autofill() -> None:
        run = store.load_run(run_id)
        if str(run.get("phase") or "") != WHOLE_OUTPUT_REVIEW:
            return
        if not whole_output_gate_state["initial"]:
            _whole_output_initial_respond()
            whole_output_gate_state["initial"] = True
            return
        if not state["whole_output"]:
            _whole_output_scope_respond()

    def _autofill_mutate() -> None:
        run = store.load_run(run_id)
        phase = str(run.get("phase") or "")
        if phase == PRODUCTION:
            _record_owner_actions()
            if not state["finding_actions"]:
                return
            if not state["verified"]:
                _verify_focused_review()
            _complete_item_second()
            return
        if phase == WHOLE_OUTPUT_REVIEW:
            _whole_output_autofill()

    factory.register_autofill_mutate(_autofill_mutate)


def seed_focused_plan_owner_pending(
    store: FileRunStore,
    *,
    run_id: str,
    loop_id: str = "review-focused-plan-01",
) -> str:
    create_planning_run(store, run_id)
    loop = focused_owner_revision_pending_loop(item_ids=["item-api"])
    loop["id"] = loop_id
    loop["type"] = "focused_plan"
    loop["scope"] = {"kind": "focused_plan", "item_ids": ["item-api"]}
    loop["target_revision"] = 0
    loop["finding_actions"] = []
    save_review_payload(store, run_id, loop)
    return loop_id


def script_focused_plan_through_plan_target(
    factory: RotatingStubProviderFactory,
    store: FileRunStore,
    run_id: str,
    loop_id: str,
) -> None:
    state = {"finding_actions": False, "verified": False}

    def _owner_plan_revision() -> None:
        if state["finding_actions"]:
            return
        base_revision = int(store.load_plan_model(run_id).revision)
        apply_plan_and_complete_focused_owner_revision(
            store,
            run_id,
            base_revision=base_revision,
            operations=with_root_contract(
                [
                    {
                        "op": "update_item",
                        "item_id": "item-api",
                        "patch": {
                            "outcome": "REST API endpoints exist.",
                            "acceptance": ["GET /health returns 200."],
                        },
                    },
                ]
            ),
            phase=PLANNING,
            loop_id=loop_id,
            role="planner",
            rationale="Owner plan revision completed.",
        )()
        state["finding_actions"] = True

    def _verify_focused_plan() -> None:
        if state["verified"]:
            return
        loop_payload = store.load_review(run_id, loop_id)
        if str(loop_payload.get("status") or "") == "approved":
            state["verified"] = True
            return
        if not state["finding_actions"]:
            return
        if str(loop_payload.get("active_stage") or "") != "finding_verification":
            return
        respond_review(
            store,
            run_id,
            {
                "loop_id": loop_id,
                "target_revision": int(loop_payload["target_revision"]),
                "stage": "finding_verification",
                "decision": "verified",
                "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
                "finding_results": [
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["acceptance criteria added"],
                        "direct_side_effects": [],
                    }
                ],
                "new_direct_side_effect_findings": [],
                "target_digest": mandatory_plan_digest(store, run_id),
                "summary": "focused plan verification",
            },
            phase=PLANNING,
            loop_id=loop_id,
        )()
        state["verified"] = True

    factory.script_turn(done_events(text="owner revision session start"))
    factory.script_turn(
        done_events(text="owner revision turn"),
        mutate_store=_owner_plan_revision,
    )
    factory.script_turn(done_events(text="recheck delivery without respond"))
    factory.script_turn(
        done_events(text="reviewer verify"),
        mutate_store=_verify_focused_plan,
    )
    factory.script_turn(done_events(signal="candidate_plan_ready", text="planning complete"))


def assert_focused_output_workflow_complete(
    store: FileRunStore,
    run_id: str,
    loop_id: str,
) -> None:
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert loop.finding_actions
    assert str(loop.status) == "approved"
    events = store.load_events(run_id)
    assert any(event.get("type") == "focused_review_approved" for event in events)
    run = store.load_run(run_id)
    assert run["status"] == "completed"
    assert run["outcome"] == "accepted"
