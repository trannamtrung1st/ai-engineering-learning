"""Shared ReviewLoopDriver tests with a fake adapter (SoT §17)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from top_down_planning.domain.models import Plan
from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop
from top_down_planning.domain.reviews import ReviewLoop, apply_discovery_response
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.mandatory_whole_review import (
    MandatoryWholeReviewResult,
    MandatoryWholeReviewSpec,
)
from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
from top_down_planning.orchestrator.review_loop_adapter_mandatory import (
    MandatoryReviewLoopAdapterMixin,
)
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.provider_turns import ProviderTurnOutcome
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import update_primary_binding
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    create_run_kwargs,
    done_events,
    enter_mandatory_verification_pending,
    ensure_plan_work_scope_contracts,
    grant_capability,
    mandatory_initial_respond_request,
    mandatory_scope_review_found_respond_request,
    mandatory_scope_review_respond_request,
    mandatory_verification_needs_revision_request,
    mandatory_verification_respond_request,
    plan_root_item,
    prepare_loop_for_scope_review_respond,
    record_finding_actions,
    respond_review,
    save_review_payload,
    seed_mandatory_interrupted_owner_revision_loop,
    seed_mandatory_scope_review_decision_loop,
    set_loop_revise_at,
    StallingAfterEventsProvider,
)


@dataclass
class _FakeAdapter(MandatoryReviewLoopAdapterMixin):
    store: FileRunStore
    run_id: str
    owner_session_id: str | None = None
    approval_result: MandatoryWholeReviewResult | None = None
    spec: MandatoryWholeReviewSpec = field(
        default_factory=lambda: MandatoryWholeReviewSpec(
            review_type="whole_plan",
            phase=WHOLE_PLAN_REVIEW,
            approved_phase=PLAN_VALIDATED,
            owner_role="planner",
            limits_key="whole_plan",
            event_prefix="whole_plan",
            loop_id_prefix="review-whole-plan",
            review_label="whole-plan review",
        )
    )

    def preflight(self, loop: ReviewLoop | None) -> None:
        return None

    def current_artifact_binding(self) -> tuple[int, str]:
        plan = self.store.load_plan(self.run_id)
        from top_down_planning.persistence.digests import compute_plan_digest

        return int(plan["revision"]), compute_plan_digest(plan)

    def new_loop(self, loop_id: str) -> ReviewLoop:
        config = self.store.load_resolved_config(self.run_id)
        revision = int(self.store.load_plan(self.run_id)["revision"])
        return new_whole_plan_review_loop(
            loop_id=loop_id,
            target_revision=revision,
            config=config,
        )

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]:
        return {"loop_id": loop.id, "type": loop.type}

    def primary_owner_session_id(self, run: dict[str, Any]) -> str | None:
        return self.owner_session_id

    def build_owner_request(
        self,
        loop: ReviewLoop,
        config: dict[str, Any],
        handoff: str,
    ) -> dict[str, Any]:
        return {"action": "address_review_findings", "loop_id": loop.id, "handoff": handoff}

    def build_owner_turn_recovery(
        self,
        phase: str,
        append_event: Any,
        model: str | None,
    ) -> Any:
        from top_down_planning.orchestrator.provider_turns import (
            build_planner_turn_recovery,
        )

        return build_planner_turn_recovery(
            self.store,
            self.run_id,
            phase=phase,
            expected_next_action="revise plan after whole-plan review",
            append_event=append_event,
            model=model,
        )

    def build_reviewer_turn_recovery(
        self,
        loop_id: str,
        phase: str,
        append_event: Any,
        model: str | None,
        review_package: dict[str, Any],
    ) -> Any:
        from top_down_planning.orchestrator.provider_turns import (
            build_reviewer_turn_recovery,
        )

        return build_reviewer_turn_recovery(
            self.store,
            self.run_id,
            loop_id=loop_id,
            phase=phase,
            expected_next_action="continue whole-plan reviewer turn",
            append_event=append_event,
            model=model,
            review_package=review_package,
        )

    def after_owner_turn(self, session_id: str) -> None:
        return None

    def complete_approval(self, loop: ReviewLoop) -> MandatoryWholeReviewResult:
        if self.approval_result is not None:
            return self.approval_result
        run = self.store.load_run(self.run_id)
        return MandatoryWholeReviewResult(
            ok=True,
            phase=str(run.get("phase") or WHOLE_PLAN_REVIEW),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            loop_id=loop.id,
            reviewer_session_id=None,
            revision_cycles=loop.revision_cycles,
        )


def _minimal_plan() -> Plan:
    return ensure_plan_work_scope_contracts(
        Plan(
            id="plan-driver",
            revision=0,
            output_goal="Goal.",
            items={"item-root": plan_root_item()},
        )
    )


def _create_driver_run(
    store: FileRunStore,
    run_id: str,
    *,
    provider: StubProvider | None = None,
    limits: dict[str, int] | None = None,
) -> tuple[str | None, str]:
    config = create_run_kwargs(store.root)["resolved_config"]
    config = dict(config)
    config["limits"] = dict(config.get("limits") or {})
    config["limits"]["whole_plan_review"] = {
        "max_revision_cycles": 5,
        "max_scope_review_rounds": 3,
    }
    if limits:
        for key, value in limits.items():
            if key in ("max_revision_cycles", "max_scope_review_rounds"):
                config["limits"]["whole_plan_review"][key] = value
                continue
            existing = config["limits"].get(key)
            if isinstance(value, dict) and isinstance(existing, dict):
                existing.update(value)
            else:
                config["limits"][key] = value
    store.create_run(
        run_id,
        plan=_minimal_plan(),
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_PLAN_REVIEW,
    )
    loop_id = "review-whole-plan-01"
    save_review_payload(
        store,
        run_id,
        {
            "id": loop_id,
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    planner_session_id = None
    if provider is not None:
        provider.script_turn(done_events(text="turn complete"))
        planner_session_id = provider.start_primary_session(
            "planner",
            {"run_id": run_id, "phase": WHOLE_PLAN_REVIEW},
        )
        list(provider.stream_events(planner_session_id))
        run = store.load_run(run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["sessions"] = update_primary_binding(
            dict(run.get("sessions") or {}),
            role="planner",
            provider_session_id=planner_session_id,
        )
        store.save_run(run_id, run, expected_revision)
    return planner_session_id, loop_id


def _minor_finding() -> dict[str, Any]:
    return {
        "id": "finding-minor-01",
        "severity": "minor",
        "category": "correctness",
        "target_refs": ["item-root"],
        "issue": "Polish wording.",
        "recommended_change": "Tighten outcome text.",
        "status": "unresolved",
    }


def _blocker_finding(*, finding_id: str = "finding-01") -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": "blocker",
        "category": "correctness",
        "target_refs": ["item-root"],
        "issue": "Needs work.",
        "recommended_change": "Improve plan.",
        "status": "unresolved",
    }


def test_driver_rejects_wrong_phase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000301-000301"
    store.create_run(
        run_id,
        plan=_minimal_plan(),
        **create_run_kwargs(tmp_path),
        phase="planning",
    )
    adapter = _FakeAdapter(store, run_id)
    with pytest.raises(ProviderRunError, match="whole-plan review"):
        ReviewLoopDriver(store, run_id, StubProvider(), adapter).run()


def test_driver_returns_already_completed_phase(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000302-000302"
    store.create_run(
        run_id,
        plan=_minimal_plan(),
        **create_run_kwargs(tmp_path),
        phase=PLAN_VALIDATED,
    )
    adapter = _FakeAdapter(store, run_id)
    result = ReviewLoopDriver(store, run_id, StubProvider(), adapter).run()
    assert result.ok is True
    assert result.phase == PLAN_VALIDATED


def test_driver_clear_approval_path_calls_adapter_complete_approval(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000303-000303"
    _, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )
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
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    assert result.loop_id == loop_id


def test_driver_blocked_reviewer_decision_terminates_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000304-000304"
    _, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id)
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
                decision="blocked",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is False
    assert result.outcome == "blocked"
    run = store.load_run(run_id)
    assert run["status"] == "completed"


def test_driver_revision_limit_pauses_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000305-000305"
    planner_session_id, loop_id = _create_driver_run(
        store,
        run_id,
        provider=provider,
        limits={"max_revision_cycles": 1},
    )
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    findings = [
        {
            "id": "finding-01",
            "severity": "blocker",
            "category": "correctness",
            "target_refs": ["item-root"],
            "issue": "Needs work.",
            "recommended_change": "Improve plan.",
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
                target_revision=0,
                review_type="whole_plan",
                decision="changes_requested",
                findings=findings,
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
                review_type="whole_plan",
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-02",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-root"],
                        "issue": "Still needs work.",
                        "recommended_change": "Improve again.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is False
    assert result.outcome is None
    assert "max_revision_cycles" in (result.reason or "")
    run = store.load_run(run_id)
    assert run["status"] == "paused"


def test_driver_verified_path_enters_scope_review_before_final_approval(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000306-000306"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    findings = [
        {
            "id": "finding-01",
            "severity": "blocker",
            "category": "correctness",
            "target_refs": ["item-root"],
            "issue": "Needs work.",
            "recommended_change": "Improve plan.",
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
                target_revision=0,
                review_type="whole_plan",
                decision="changes_requested",
                findings=findings,
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

    def _verification_respond() -> None:
        loop = store.load_review(run_id, loop_id)
        finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
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
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_verification_respond)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )(),
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("scope_review_result")
    assert review.get("verification_result")
    assert review["scope_review_rounds"] == 1


def test_driver_reuses_existing_nonterminal_loop(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000307-000307"
    _, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id)
    existing = store.load_review(run_id, loop_id)
    existing["reviewer_session_id"] = "existing-reviewer-session"
    existing["finding_set_id"] = "review-whole-plan-01-fs-01"
    save_review_payload(store, run_id, existing)
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
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    assert result.loop_id == loop_id
    assert store.load_review(run_id, loop_id)["id"] == loop_id


def test_driver_discovery_review_incomplete_pauses_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000308-000308"
    _, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id)
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    from top_down_planning.domain.reviews import allocate_discovery_finding_set_id

    loop, finding_set_id = allocate_discovery_finding_set_id(loop)
    save_review_payload(store, run_id, loop.to_dict())
    from top_down_planning.persistence.digests import compute_plan_digest

    plan = store.load_plan(run_id)
    incomplete_loop, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": finding_set_id,
            "reported_findings": [],
            "review_completed": False,
            "summary": "artifact unreadable",
            "target_digest": compute_plan_digest(plan),
        },
        stage="initial_review",
    )
    assert outcome == "review_incomplete"
    save_review_payload(store, run_id, incomplete_loop.to_dict())
    with patch.object(
        ReviewLoopDriver,
        "_normalize_loop_for_resume",
        return_value=(incomplete_loop, False),
    ):
        result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is False
    assert result.reason
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run.get("stop", {}).get("code") == "review_incomplete"
    review = store.load_review(run_id, loop_id)
    assert review.get("lifecycle_status") == "review_incomplete"


def test_driver_verification_needs_revision_enters_owner_cycle(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000309-000309"
    planner_session_id, loop_id = _create_driver_run(
        store,
        run_id,
        provider=provider,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    findings = [
        {
            "id": "finding-01",
            "severity": "blocker",
            "category": "correctness",
            "target_refs": ["item-root"],
            "issue": "Needs work.",
            "recommended_change": "Improve plan.",
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
                target_revision=0,
                review_type="whole_plan",
                decision="changes_requested",
                findings=findings,
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
                        "disposition": "partially_resolved",
                        "evidence": ["partial fix"],
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
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=1,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"outcome": "Fully improved outcome."},
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )
    provider.script_turn(done_events(text="turn complete"))
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is False
    assert store.load_run(run_id)["stop"]["code"] == "limit_exhausted"
    review = store.load_review(run_id, loop_id)
    assert review["lifecycle_status"] == "verification_pending"
    assert review["revision_cycles"] == 2


def test_driver_scope_review_round_limit_pauses(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000310-000310"
    planner_session_id, loop_id = _create_driver_run(
        store,
        run_id,
        provider=provider,
        limits={"max_revision_cycles": 5, "max_scope_review_rounds": 1},
    )
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    blocker = {
        "id": "finding-blocker-01",
        "severity": "blocker",
        "category": "correctness",
        "target_refs": ["item-root"],
        "issue": "Still blocked.",
        "recommended_change": "Fix coverage.",
        "status": "unresolved",
    }

    def _scope_found_respond() -> None:
        loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
        if loop.active_stage != "scope_review":
            prepare_loop_for_scope_review_respond(
                store,
                run_id,
                loop_id,
                target_revision=0,
            )
        respond_review(
            store,
            run_id,
            mandatory_scope_review_found_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
                findings=[blocker],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

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
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_found_respond)
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

    def _verification_respond() -> None:
        loop = store.load_review(run_id, loop_id)
        finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
        enter_mandatory_verification_pending(
            store,
            run_id,
            loop_id,
            target_revision=1,
            finding_set_id=finding_set_id,
        )
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-blocker-01",
                        "disposition": "resolved",
                        "evidence": ["fixed"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=_verification_respond,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is False
    assert result.status == "paused"
    assert "max_scope_review_rounds" in (result.reason or "")
    run = store.load_run(run_id)
    assert run.get("stop", {}).get("code") == "limit_exhausted"
    review = store.load_review(run_id, loop_id)
    assert review.get("lifecycle_status") == "limit_reached"


def test_driver_continues_same_loop_after_scope_limit_extension(tmp_path: Path) -> None:
    """Raising max_scope_review_rounds resumes the same loop with preserved rounds."""

    import copy

    from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
    from top_down_planning.orchestrator.prepare_resume import prepare_resume

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000410-000410"
    planner_session_id, loop_id = _create_driver_run(
        store,
        run_id,
        provider=provider,
        limits={"max_revision_cycles": 5, "max_scope_review_rounds": 1},
    )
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)

    # Seed a limit_reached loop that already consumed one scope round.
    save_review_payload(
        store,
        run_id,
        {
            "id": loop_id,
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "blocked",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "limit_reached",
            "active_stage": "finding_verification",
            "scope_review_rounds": 1,
            "exhausted_budget": "scope_review",
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": WHOLE_PLAN_REVIEW,
        "message": "whole-plan review exceeded max_scope_review_rounds (1)",
        "details": {
            "limit": "limits.whole_plan_review.max_scope_review_rounds",
            "consumed": 1,
            "configured": 1,
            "loop_id": loop_id,
            "exhausted_budget": "scope_review",
        },
    }
    store.save_run(run_id, run, expected_revision)

    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"]["whole_plan_review"]["max_scope_review_rounds"] = 3
    resume_plan = prepare_resume(store, run_id, candidate)
    apply_resume_plan_atomically(
        store,
        resume_plan,
        resolved_config=candidate,
        invocation=store.load_invocation(run_id),
    )

    review_after_apply = store.load_review(run_id, loop_id)
    assert review_after_apply["scope_review_rounds"] == 1
    assert review_after_apply["lifecycle_status"] == "findings_closed"

    def _scope_approve() -> None:
        loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
        if loop.active_stage != "scope_review":
            prepare_loop_for_scope_review_respond(
                store,
                run_id,
                loop_id,
                target_revision=0,
            )
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_approve)
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    assert result.loop_id == loop_id
    review = store.load_review(run_id, loop_id)
    assert review["scope_review_rounds"] == 2
    assert review.get("exhausted_budget") is None
    whole_plan_loops = [
        payload
        for payload in store.list_reviews(run_id)
        if payload.get("type") == "whole_plan"
    ]
    assert [payload["id"] for payload in whole_plan_loops] == [loop_id]


def test_get_or_create_does_not_resurrect_older_limit_reached_after_approved(
    tmp_path: Path,
) -> None:
    """A newer approved whole-plan loop must not revive an older limit_reached."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000411-000411"
    planner_session_id, _loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    revision, _digest = adapter.current_artifact_binding()

    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": revision,
            "scope": {"kind": "whole_plan"},
            "status": "blocked",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "limit_reached",
            "active_stage": None,
            "scope_review_rounds": 1,
            "exhausted_budget": "scope_review",
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-plan-02",
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": revision,
            "scope": {"kind": "whole_plan"},
            "status": "approved",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "approved",
            "active_stage": "scope_review",
            "scope_review_rounds": 1,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )

    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    selected = driver._get_or_create_active_loop()
    assert selected.id == "review-whole-plan-03"
    assert selected.lifecycle_status != "limit_reached"


def test_get_or_create_prefers_newer_active_over_older_limit_reached(
    tmp_path: Path,
) -> None:
    """Do not walk past a newer non-terminal loop to an older limit_reached."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000412-000412"
    planner_session_id, _loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)

    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "blocked",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "limit_reached",
            "scope_review_rounds": 1,
            "exhausted_budget": "scope_review",
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-plan-02",
            "type": "whole_plan",
            "revise_at": "blocker",
            "target_revision": 0,  # lags current artifact revision
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )

    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    selected = driver._get_or_create_active_loop()
    assert selected.id == "review-whole-plan-02"
    assert selected.lifecycle_status == "review_pending"


def test_driver_unexpected_decision_raises_provider_error(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000311-000311"
    _, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id)
    seed_mandatory_scope_review_decision_loop(store, run_id, loop_id)
    with patch(
        "top_down_planning.orchestrator.review_loop_driver.mandatory_orchestration_decision",
        return_value="corrupted",
    ):
        with pytest.raises(ProviderRunError, match="unexpected mandatory review decision"):
            ReviewLoopDriver(store, run_id, provider, adapter).run()


def test_driver_advisory_pending_defer_enters_scope_review(tmp_path: Path) -> None:
    """Minor-only discovery enters advisory handoff; owner defer skips verification."""
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000312-000312"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    from top_down_planning.domain.reviews import (
        ReviewLoop,
        allocate_discovery_finding_set_id,
        apply_discovery_response,
        apply_owner_finding_actions,
        complete_advisory_handoff_if_owner_responses_recorded,
        needs_advisory_handoff,
    )
    from top_down_planning.persistence.digests import compute_plan_digest

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    loop = set_loop_revise_at(store, run_id, loop_id, revise_at="major")
    loop, finding_set_id = allocate_discovery_finding_set_id(loop)
    loop, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": finding_set_id,
            "reported_findings": [_minor_finding()],
            "review_completed": True,
            "summary": "minor only",
            "target_digest": compute_plan_digest(store.load_plan(run_id)),
        },
        stage="initial_review",
    )
    assert outcome == "pending"
    assert loop.status == "advisory_pending"
    assert needs_advisory_handoff(loop)
    loop, _actions = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": str(loop.findings[0].id),
                "action": "defer",
                "rationale": "Defer polish",
                "finding_set_id": finding_set_id,
            }
        ],
        actor_role="planner",
        artifact_revision=0,
    )
    assert loop.status == "approved"
    assert not needs_advisory_handoff(loop)
    loop = complete_advisory_handoff_if_owner_responses_recorded(loop)
    save_review_payload(store, run_id, loop.to_dict())
    persisted = store.load_review(run_id, loop_id)
    assert persisted["status"] == "approved"
    assert persisted.get("advisory_handoffs_completed")

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("advisory_handoffs_completed")
    assert review["revision_cycles"] == 0
    assert review.get("scope_review_result")


def test_driver_orchestrates_advisory_defer_through_scope(tmp_path: Path) -> None:
    """Full driver path: discovery → owner defer → scope clear (no domain pre-seed)."""
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000316-000316"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    set_loop_revise_at(store, run_id, loop_id, revise_at="major")
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    from top_down_planning.agent_tool import ReviewAgentService

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
                findings=[_minor_finding()],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )

    def _planner_defers() -> None:
        persisted = store.load_review(run_id, loop_id)
        token = grant_capability(
            store,
            run_id,
            role="planner",
            phase=WHOLE_PLAN_REVIEW,
            session_id=planner_session_id,
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "artifact_revision": 0,
                "finding_actions": [
                    {
                        "finding_id": "finding-minor-01",
                        "action": "defer",
                        "actor_role": "planner",
                        "artifact_revision": 0,
                        "finding_set_id": persisted["finding_set_id"],
                        "rationale": "Defer polish",
                    }
                ],
            },
            capability_token=token,
        )

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="deferred"), mutate_store=_planner_defers)
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("advisory_handoffs_completed")
    assert review["revision_cycles"] == 0
    assert review.get("scope_review_result")


def test_driver_advisory_handoff_closes_on_record_actions_while_stream_stalls(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StallingAfterEventsProvider()
    run_id = "run-20260101T000316-000316"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    set_loop_revise_at(store, run_id, loop_id, revise_at="major")
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    from top_down_planning.agent_tool import ReviewAgentService

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
                findings=[_minor_finding()],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )

    def _planner_defers() -> None:
        persisted = store.load_review(run_id, loop_id)
        token = grant_capability(
            store,
            run_id,
            role="planner",
            phase=WHOLE_PLAN_REVIEW,
            session_id=planner_session_id,
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "artifact_revision": 0,
                "finding_actions": [
                    {
                        "finding_id": "finding-minor-01",
                        "action": "defer",
                        "actor_role": "planner",
                        "artifact_revision": 0,
                        "finding_set_id": persisted["finding_set_id"],
                        "rationale": "Defer polish",
                    }
                ],
            },
            capability_token=token,
        )

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(
        [
            {"type": "assistant", "text": "deferring optional finding"},
            {"type": "assistant", "text": "still streaming without done"},
        ],
        mutate_store=_planner_defers,
    )
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )

    result = ReviewLoopDriver(store, run_id, provider, adapter).run()

    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("advisory_handoffs_completed")


def test_driver_scope_review_advisory_handoff_requires_reviewer_clear(
    tmp_path: Path,
) -> None:
    """Scope-review optional findings: owner accept must route to reviewer scope clear."""
    from dataclasses import replace

    from top_down_planning.agent_tool import ReviewAgentService
    from top_down_planning.domain.reviews import (
        ReviewLoop,
        allocate_discovery_finding_set_id,
        apply_discovery_response,
        needs_advisory_handoff,
        scope_review_approval_recorded,
    )
    from top_down_planning.persistence.digests import compute_plan_digest

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000317-000317"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    set_loop_revise_at(store, run_id, loop_id, revise_at="major")
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    loop, finding_set_id = allocate_discovery_finding_set_id(loop)
    loop = replace(
        loop,
        active_stage="scope_review",
        lifecycle_status="scope_review_pending",
        scope_review_rounds=1,
    )
    loop, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": finding_set_id,
            "reported_findings": [_minor_finding()],
            "review_completed": True,
            "summary": "minor only at scope review",
            "target_digest": compute_plan_digest(store.load_plan(run_id)),
        },
        stage="scope_review",
    )
    assert outcome == "pending"
    assert loop.status == "advisory_pending"
    assert loop.active_stage == "scope_review"
    assert needs_advisory_handoff(loop)
    assert not scope_review_approval_recorded(loop)
    save_review_payload(store, run_id, loop.to_dict())

    def _planner_accepts() -> None:
        persisted = store.load_review(run_id, loop_id)
        token = grant_capability(
            store,
            run_id,
            role="planner",
            phase=WHOLE_PLAN_REVIEW,
            session_id=planner_session_id,
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "artifact_revision": 0,
                "finding_actions": [
                    {
                        "finding_id": "finding-minor-01",
                        "action": "accept_as_is",
                        "actor_role": "planner",
                        "artifact_revision": 0,
                        "finding_set_id": persisted["finding_set_id"],
                        "rationale": "Accept optional polish items.",
                    }
                ],
            },
            capability_token=token,
        )

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="accepted"), mutate_store=_planner_accepts)
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("advisory_handoffs_completed")
    assert review.get("scope_review_result")
    assert scope_review_approval_recorded(ReviewLoop.from_dict(review))


def test_driver_resumes_owner_approved_scope_review_without_result(
    tmp_path: Path,
) -> None:
    """Resume path: finding policy approved at scope_review without scope_review_result."""
    from dataclasses import replace

    from top_down_planning.domain.reviews import (
        ReviewLoop,
        allocate_discovery_finding_set_id,
        apply_discovery_response,
        apply_owner_finding_actions,
        complete_advisory_handoff_if_owner_responses_recorded,
        mandatory_stage_respond_decision,
    )
    from top_down_planning.persistence.digests import compute_plan_digest

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000318-000318"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    set_loop_revise_at(store, run_id, loop_id, revise_at="major")
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    loop, finding_set_id = allocate_discovery_finding_set_id(loop)
    loop = replace(
        loop,
        active_stage="scope_review",
        lifecycle_status="scope_review_pending",
        scope_review_rounds=1,
    )
    loop, _, _outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": finding_set_id,
            "reported_findings": [_minor_finding()],
            "review_completed": True,
            "summary": "minor only at scope review",
            "target_digest": compute_plan_digest(store.load_plan(run_id)),
        },
        stage="scope_review",
    )
    loop, _actions = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": "finding-minor-01",
                "action": "accept_as_is",
                "actor_role": "planner",
                "artifact_revision": 0,
                "finding_set_id": finding_set_id,
                "rationale": "Accept optional polish items.",
            }
        ],
        actor_role="planner",
        artifact_revision=0,
    )
    loop = complete_advisory_handoff_if_owner_responses_recorded(loop)
    loop = replace(loop, advisory_handoffs_completed=[finding_set_id])
    save_review_payload(store, run_id, loop.to_dict())
    persisted = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    assert persisted.status == "approved"
    assert persisted.scope_review_result is None
    assert mandatory_stage_respond_decision(persisted) == "pending"

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("scope_review_result")


def test_driver_interrupted_owner_revision_resumes_recheck(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000313-000313"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=0,
            review_type="whole_plan",
            decision="changes_requested",
            findings=[_blocker_finding()],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id=loop_id,
    )()
    seed_mandatory_interrupted_owner_revision_loop(store, run_id, loop_id)

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

    def _verification_respond() -> None:
        loop = store.load_review(run_id, loop_id)
        finding_set_id = str(loop.get("finding_set_id") or f"{loop_id}-fs-01")
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
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
            loop_id=loop_id,
        )()

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_verification_respond)
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=1,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("verification_result")
    assert review["revision_cycles"] == 1


def test_driver_challenge_only_enters_verification_not_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000314-000314"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    from top_down_planning.agent_tool import ReviewAgentService
    from top_down_planning.domain.reviews import (
        ReviewLoop,
        allocate_discovery_finding_set_id,
        apply_discovery_response,
    )
    from top_down_planning.persistence.digests import compute_plan_digest

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    loop = set_loop_revise_at(store, run_id, loop_id, revise_at="major")
    loop, finding_set_id = allocate_discovery_finding_set_id(loop)
    loop, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": finding_set_id,
            "reported_findings": [_minor_finding()],
            "review_completed": True,
            "summary": "minor only",
            "target_digest": compute_plan_digest(store.load_plan(run_id)),
        },
        stage="initial_review",
    )
    assert outcome == "pending"
    finding_id = str(loop.findings[0].id)
    payload = loop.to_dict()
    payload["reviewer_session_id"] = "reviewer-seed-01"
    save_review_payload(store, run_id, payload)

    def _planner_challenges() -> None:
        persisted = store.load_review(run_id, loop_id)
        token = grant_capability(
            store,
            run_id,
            role="planner",
            phase=WHOLE_PLAN_REVIEW,
            session_id=planner_session_id,
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "artifact_revision": 0,
                "finding_actions": [
                    {
                        "finding_id": finding_id,
                        "action": "challenge",
                        "actor_role": "planner",
                        "artifact_revision": 0,
                        "finding_set_id": persisted["finding_set_id"],
                        "challenge_reason": "invalid",
                        "rationale": "not actionable",
                        "proposed_disposition": "invalid",
                    }
                ],
            },
            capability_token=token,
        )

    def _verification_respond() -> None:
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": finding_id,
                        "disposition": "invalid",
                        "evidence": ["challenge accepted"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(
        done_events(text="challenged"),
        mutate_store=_planner_challenges,
    )
    provider.script_turn(done_events(text="deliver verification package"))
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=_verification_respond,
    )
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert result.ok is True
    review = store.load_review(run_id, loop_id)
    assert review.get("verification_result")
    assert review["revision_cycles"] == 0
    assert int(store.load_plan(run_id)["revision"]) == 0


def test_driver_reviewer_session_replace_adopts_capability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000315-000315"
    _, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id)

    def _initial_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_initial_clear)
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=0,
    )

    import top_down_planning.orchestrator.review_loop_driver as driver_module

    real_consume = driver_module.consume_reviewer_provider_turn_with_session_recovery
    consume_calls = 0

    def _consume_side_effect(*args: Any, **kwargs: Any) -> ProviderTurnOutcome:
        nonlocal consume_calls
        consume_calls += 1
        if consume_calls == 1:
            real_consume(*args, **kwargs)
            return ProviderTurnOutcome(
                signal=None,
                session_id="replacement-reviewer-session",
                replaced=True,
                capability_token="replacement-capability-token",
            )
        return real_consume(*args, **kwargs)

    with patch.object(
        driver_module,
        "consume_reviewer_provider_turn_with_session_recovery",
        side_effect=_consume_side_effect,
    ) as consume_turn:
        with patch.object(
            driver_module,
            "adopt_replacement_capability",
            return_value="replacement-capability-token",
        ) as adopt_capability:
            result = ReviewLoopDriver(store, run_id, provider, adapter).run()

    assert consume_calls >= 1
    adopt_capability.assert_called_once()
    assert result.ok is True
