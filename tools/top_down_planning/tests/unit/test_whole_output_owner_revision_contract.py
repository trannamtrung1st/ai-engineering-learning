"""Owner-revision contract: claim preflight, turn boundary, and atomic apply."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderTurnError
from top_down_planning.orchestrator.errors import CompletionClaimRequired
from top_down_planning.orchestrator.whole_output_review import OutputWholeReviewAdapter
from top_down_planning.domain.reviews import (
    FindingAction,
    ReviewFinding,
    ReviewLoop,
    pending_interrupted_owner_revision,
    required_findings_missing_owner_response,
)
from top_down_planning.orchestrator import WholeOutputReviewOrchestrator
from top_down_planning.orchestrator.provider_turns import owner_revision_complete
from top_down_planning.orchestrator.mandatory_review_stages import (
    enter_owner_revision_cycle,
    mark_findings_open,
)
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from tests.helpers import (
    apply_production,
    done_events,
    mandatory_initial_respond_request,
    mandatory_scope_review_respond_request,
    mandatory_verification_respond_request,
    record_finding_actions,
    record_mandatory_owner_revision_complete,
    respond_review,
    save_review_payload,
)
from tests.support.whole_output_review import create_run_at_whole_output_review as _create_run_at_whole_output_review


_RUN_ID = "run-20260101T000801-000801"
_LOOP_ID = "review-whole-output-01"
_FINDING_SET_ID = "review-whole-output-01-fs-01"


def _blocker_finding() -> ReviewFinding:
    return ReviewFinding(
        id="finding-01",
        severity="blocker",
        category="correctness",
        target_refs=["item-leaf"],
        issue="Output evidence is missing.",
        recommended_change="Add artifact reference.",
        status="unresolved",
    )


def _clear_completion_claim(store: FileRunStore, run_id: str) -> None:
    production = store.load_production(run_id)
    expected = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["completion_claim"] = None
    store.save_production(run_id, updated, expected)


def _enter_owner_revision_in_progress(store: FileRunStore, run_id: str) -> ReviewLoop:
    loop = ReviewLoop.from_dict(store.load_review(run_id, _LOOP_ID))
    loop = replace(
        loop,
        findings=[_blocker_finding()],
        finding_set_id=_FINDING_SET_ID,
        finding_ids_by_set={_FINDING_SET_ID: ["finding-01"]},
    )
    loop = mark_findings_open(loop)
    loop = enter_owner_revision_cycle(replace(loop, revision_cycles=1))
    save_review_payload(store, run_id, loop.to_dict())
    return ReviewLoop.from_dict(store.load_review(run_id, _LOOP_ID))


def _record_required_fix(store: FileRunStore, run_id: str) -> None:
    record_mandatory_owner_revision_complete(
        store,
        run_id,
        loop_id=_LOOP_ID,
        phase=WHOLE_OUTPUT_REVIEW,
        role="producer",
        changed_refs=["item-leaf"],
        searched_refs=["production:*"],
        rationale="Added missing evidence.",
    )


def _evidence_revision_request(*, production_revision: int, with_completion: bool) -> dict:
    payload: dict = {
        "production_revision": production_revision,
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
        "goal_assessment": "Output goal is fully met after revision.",
    }
    if with_completion:
        payload["completion"] = {
            "goal_met": True,
            "summary": "Revised evidence satisfies the output goal.",
        }
    return payload


def test_required_findings_missing_owner_response_until_fix_recorded() -> None:
    findings = [_blocker_finding()]
    missing = required_findings_missing_owner_response(
        findings,
        [],
        "blocker",
        finding_set_id=_FINDING_SET_ID,
    )
    assert [finding.id for finding in missing] == ["finding-01"]

    recorded = [
        FindingAction(
            finding_id="finding-01",
            action="fix",
            actor_role="producer",
            artifact_revision=2,
            finding_set_id=_FINDING_SET_ID,
            rationale="Fixed.",
        )
    ]
    assert (
        required_findings_missing_owner_response(
            findings,
            recorded,
            "blocker",
            finding_set_id=_FINDING_SET_ID,
        )
        == []
    )


def test_pending_interrupted_owner_revision_stays_pending_after_artifact_bump() -> None:
    loop = _blocker_finding()
    review = ReviewLoop.from_dict(
        {
            "id": _LOOP_ID,
            "type": "whole_output",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [loop.to_dict()],
            "revision_cycles": 1,
            "revise_at": "blocker",
            "lifecycle_status": "revision_in_progress",
            "active_stage": "finding_verification",
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        }
    )

    assert pending_interrupted_owner_revision(review, current_revision=1) is True
    assert pending_interrupted_owner_revision(review, current_revision=2) is True


def test_fresh_whole_output_entry_without_claim_pauses_completion_claim_required(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    _clear_completion_claim(store, _RUN_ID)

    result = WholeOutputReviewOrchestrator(store, _RUN_ID, provider).run()

    assert result.ok is False
    run = store.load_run(_RUN_ID)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "completion_claim_required"
    assert run["stop"]["category"] == "operational"
    assert run["stop"]["role"] == "producer"
    assert run["stop"]["details"]["next_actor"] == "producer"
    assert run["stop"]["details"]["current_output_revision"] == 1
    assert store.load_review(_RUN_ID, _LOOP_ID)["lifecycle_status"] == "review_pending"


def test_whole_output_revision_in_progress_without_claim_resumes_owner(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    loop = _enter_owner_revision_in_progress(store, _RUN_ID)
    _clear_completion_claim(store, _RUN_ID)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")
    assert loop.lifecycle_status == "revision_in_progress"
    assert store.load_production(_RUN_ID)["completion_claim"] is None

    def _owner_revision() -> None:
        production = store.load_production(_RUN_ID)
        apply_production(
            store,
            _RUN_ID,
            _evidence_revision_request(
                production_revision=int(production["revision"]),
                with_completion=True,
            ),
            handler="apply",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        _record_required_fix(store, _RUN_ID)

    provider.script_turn(done_events(text="owner revision"), mutate_store=_owner_revision)

    def _verification_respond() -> None:
        loop_payload = store.load_review(_RUN_ID, _LOOP_ID)
        finding_set_id = str(loop_payload.get("finding_set_id") or _FINDING_SET_ID)
        target_revision = int(store.load_production(_RUN_ID)["output_revision"])
        respond_review(
            store,
            _RUN_ID,
            mandatory_verification_respond_request(
                store,
                _RUN_ID,
                loop_id=_LOOP_ID,
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
            loop_id=_LOOP_ID,
        )()

    provider.script_turn(
        done_events(text="verification complete"),
        mutate_store=_verification_respond,
    )

    def _scope_respond() -> None:
        target_revision = int(store.load_production(_RUN_ID)["output_revision"])
        respond_review(
            store,
            _RUN_ID,
            mandatory_scope_review_respond_request(
                store,
                _RUN_ID,
                loop_id=_LOOP_ID,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=_LOOP_ID,
        )()

    provider.script_turn(done_events(text="scope review complete"), mutate_store=_scope_respond)

    result = WholeOutputReviewOrchestrator(store, _RUN_ID, provider).run()

    assert result.ok is True
    assert result.outcome == "accepted"
    production = store.load_production(_RUN_ID)
    assert production["completion_claim"]["goal_met"] is True
    assert production["completion_claim"]["output_revision"] == production["output_revision"]


def test_evidence_revision_apply_with_completion_stamps_claim_for_new_output_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    _enter_owner_revision_in_progress(store, _RUN_ID)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    before = store.load_production(_RUN_ID)
    apply_production(
        store,
        _RUN_ID,
        _evidence_revision_request(
            production_revision=int(before["revision"]),
            with_completion=True,
        ),
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    production = store.load_production(_RUN_ID)
    claim = production["completion_claim"]
    assert production["output_revision"] == int(before["output_revision"]) + 1
    assert claim["goal_met"] is True
    assert claim["output_revision"] == production["output_revision"]
    assert claim["plan_revision"] == 0
    assert claim["goal_assessment"] == "Output goal is fully met after revision."
    assert claim["summary"] == "Revised evidence satisfies the output goal."
    assert claim["owner_revision_cycle"] == 1
    assert int(production["revision"]) == int(before["revision"]) + 1
    events = store.load_events(_RUN_ID)
    assert sum(1 for event in events if event.get("type") == "production_completion_claimed") == 1


def test_owner_revision_complete_rejects_prior_cycle_actions_with_same_finding_set(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import owner_revision_complete

    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    loop = _enter_owner_revision_in_progress(store, _RUN_ID)
    loop = replace(
        loop,
        revision_cycles=2,
        lifecycle_status="revision_in_progress",
        status="pending",
        verification_result={"decision": "needs_revision"},
        finding_actions=[
            FindingAction(
                finding_id="finding-01",
                action="fix",
                actor_role="producer",
                artifact_revision=2,
                finding_set_id=_FINDING_SET_ID,
                rationale="Cycle 1 fix.",
                owner_revision_cycle=1,
            )
        ],
    )
    save_review_payload(store, _RUN_ID, loop.to_dict())
    production = store.load_production(_RUN_ID)
    expected = int(production["revision"])
    claim = dict(production.get("completion_claim") or {})
    claim["owner_revision_cycle"] = 1
    updated = dict(production)
    updated["revision"] = expected + 1
    updated["completion_claim"] = claim
    store.save_production(_RUN_ID, updated, expected)

    assert owner_revision_complete(store, _RUN_ID, _LOOP_ID) is False


def _seed_cycle_one_owner_revision_complete(store: FileRunStore) -> None:
    _enter_owner_revision_in_progress(store, _RUN_ID)
    artifacts_dir = store.root / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")
    production = store.load_production(_RUN_ID)
    apply_production(
        store,
        _RUN_ID,
        _evidence_revision_request(
            production_revision=int(production["revision"]),
            with_completion=True,
        ),
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    _record_required_fix(store, _RUN_ID)


def _seed_verification_needs_revision_crash_window(store: FileRunStore) -> None:
    """Crash after mark_findings_open but before enter_revision_cycle charged cycle 2."""

    loop = ReviewLoop.from_dict(store.load_review(_RUN_ID, _LOOP_ID))
    loop = replace(
        loop,
        revision_cycles=1,
        lifecycle_status="revision_in_progress",
        status="needs_revision",
        verification_result={"decision": "needs_revision"},
    )
    save_review_payload(store, _RUN_ID, loop.to_dict())


def test_resume_crash_window_at_revision_limit_pauses_without_producer(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(
        store,
        provider=provider,
        limits={"max_revision_cycles": 1},
    )
    _seed_cycle_one_owner_revision_complete(store)
    _seed_verification_needs_revision_crash_window(store)

    owner_turn_started = False

    def _unexpected_owner_turn() -> None:
        nonlocal owner_turn_started
        owner_turn_started = True

    provider.script_turn(
        done_events(text="should not run"),
        mutate_store=_unexpected_owner_turn,
    )

    result = WholeOutputReviewOrchestrator(store, _RUN_ID, provider).run()

    assert owner_turn_started is False
    assert result.ok is False
    review = store.load_review(_RUN_ID, _LOOP_ID)
    assert review["revision_cycles"] == 1
    assert review["lifecycle_status"] == "limit_reached"
    assert review["exhausted_budget"] == "verification_revision"
    run = store.load_run(_RUN_ID)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "limit_exhausted"


def test_resume_after_verification_needs_revision_crash_window_runs_cycle_two_producer(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    _seed_cycle_one_owner_revision_complete(store)
    _seed_verification_needs_revision_crash_window(store)

    assert owner_revision_complete(store, _RUN_ID, _LOOP_ID) is True
    cycles_before = int(store.load_review(_RUN_ID, _LOOP_ID)["revision_cycles"])

    owner_turn_started = False

    def _cycle_two_owner_revision() -> None:
        nonlocal owner_turn_started
        owner_turn_started = True
        apply_production(
            store,
            _RUN_ID,
            {"goal_assessment": "Output goal remains met after cycle 2."},
            handler="submit_completion",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        _record_required_fix(store, _RUN_ID)

    provider.script_turn(
        done_events(text="cycle 2 owner revision"),
        mutate_store=_cycle_two_owner_revision,
    )
    provider.script_turn(done_events(text="reviewer recheck"))

    with pytest.raises(ProviderTurnError, match="no scripted provider turn"):
        WholeOutputReviewOrchestrator(store, _RUN_ID, provider).run()

    loop_after = ReviewLoop.from_dict(store.load_review(_RUN_ID, _LOOP_ID))
    assert owner_turn_started is True
    assert loop_after.revision_cycles == cycles_before + 1
    assert owner_revision_complete(store, _RUN_ID, _LOOP_ID) is True
    cycle_two_actions = [
        action
        for action in loop_after.finding_actions
        if action.owner_revision_cycle == 2 and action.action == "fix"
    ]
    assert [action.finding_id for action in cycle_two_actions] == ["finding-01"]


def test_resume_cycle_two_runs_producer_before_reviewer_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    _enter_owner_revision_in_progress(store, _RUN_ID)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    production = store.load_production(_RUN_ID)
    apply_production(
        store,
        _RUN_ID,
        _evidence_revision_request(
            production_revision=int(production["revision"]),
            with_completion=True,
        ),
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    _record_required_fix(store, _RUN_ID)
    loop = ReviewLoop.from_dict(store.load_review(_RUN_ID, _LOOP_ID))
    loop = replace(
        loop,
        revision_cycles=2,
        lifecycle_status="revision_in_progress",
        status="pending",
        verification_result={"decision": "needs_revision"},
    )
    save_review_payload(store, _RUN_ID, loop.to_dict())
    assert owner_revision_complete(store, _RUN_ID, _LOOP_ID) is False

    owner_turn_started = False
    verification_started = False

    def _cycle_two_owner_revision() -> None:
        nonlocal owner_turn_started
        owner_turn_started = True
        apply_production(
            store,
            _RUN_ID,
            {"goal_assessment": "Output goal remains met after cycle 2."},
            handler="submit_completion",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        _record_required_fix(store, _RUN_ID)

    provider.script_turn(
        done_events(text="cycle 2 owner revision"),
        mutate_store=_cycle_two_owner_revision,
    )

    def _verification_respond() -> None:
        nonlocal verification_started
        verification_started = True
        loop_payload = store.load_review(_RUN_ID, _LOOP_ID)
        finding_set_id = str(loop_payload.get("finding_set_id") or _FINDING_SET_ID)
        target_revision = int(store.load_production(_RUN_ID)["output_revision"])
        respond_review(
            store,
            _RUN_ID,
            mandatory_verification_respond_request(
                store,
                _RUN_ID,
                loop_id=_LOOP_ID,
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
            loop_id=_LOOP_ID,
        )()

    provider.script_turn(
        done_events(text="verification complete"),
        mutate_store=_verification_respond,
    )

    with pytest.raises(ProviderTurnError, match="no scripted provider turn"):
        WholeOutputReviewOrchestrator(store, _RUN_ID, provider).run()

    assert owner_turn_started is True
    assert verification_started is True
    loop_after = ReviewLoop.from_dict(store.load_review(_RUN_ID, _LOOP_ID))
    assert loop_after.revision_cycles == 2
    assert owner_revision_complete(store, _RUN_ID, _LOOP_ID) is True
    cycle_two_actions = [
        action
        for action in loop_after.finding_actions
        if action.owner_revision_cycle == 2 and action.action == "fix"
    ]
    assert [action.finding_id for action in cycle_two_actions] == ["finding-01"]
    claim = store.load_production(_RUN_ID)["completion_claim"]
    assert claim["owner_revision_cycle"] == 2


def test_fresh_whole_output_entry_rejects_stale_completion_claim(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    adapter = OutputWholeReviewAdapter(store, _RUN_ID)
    production = dict(store.load_production(_RUN_ID))
    claim = dict(production.get("completion_claim") or {})
    claim["plan_revision"] = int(claim.get("plan_revision", 0)) + 99
    production["completion_claim"] = claim

    with patch.object(adapter._store, "load_production", return_value=production):
        with pytest.raises(CompletionClaimRequired):
            adapter._require_completion_claim()


def test_completion_claim_does_not_change_output_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    _enter_owner_revision_in_progress(store, _RUN_ID)

    before = store.load_production(_RUN_ID)
    before_digest = compute_output_digest(before)
    before_output_revision = int(before["output_revision"])
    before_production_revision = int(before["revision"])

    apply_production(
        store,
        _RUN_ID,
        {
            "goal_assessment": "Output goal remains fully met.",
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    after = store.load_production(_RUN_ID)

    assert int(after["revision"]) == before_production_revision + 1
    assert int(after["output_revision"]) == before_output_revision
    assert compute_output_digest(after) == before_digest


def test_evidence_revision_changes_output_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    _enter_owner_revision_in_progress(store, _RUN_ID)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    before_digest = compute_output_digest(store.load_production(_RUN_ID))

    production = store.load_production(_RUN_ID)
    apply_production(
        store,
        _RUN_ID,
        _evidence_revision_request(
            production_revision=int(production["revision"]),
            with_completion=False,
        ),
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    after_digest = compute_output_digest(store.load_production(_RUN_ID))

    assert after_digest != before_digest


def test_owner_sweep_survives_submit_completion_for_verification(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
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
        done_events(text="initial review complete"),
        mutate_store=respond_review(
            store,
            _RUN_ID,
            mandatory_initial_respond_request(
                store,
                _RUN_ID,
                loop_id=_LOOP_ID,
                target_revision=1,
                review_type="whole_output",
                decision="changes_requested",
                findings=findings,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=_LOOP_ID,
        ),
    )

    revision_cycles_before = int(store.load_review(_RUN_ID, _LOOP_ID)["revision_cycles"])

    def _producer_revision() -> None:
        production = store.load_production(_RUN_ID)
        apply_production(
            store,
            _RUN_ID,
            _evidence_revision_request(
                production_revision=int(production["revision"]),
                with_completion=False,
            ),
            handler="apply",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        digest_at_sweep = compute_output_digest(store.load_production(_RUN_ID))
        output_revision = int(store.load_production(_RUN_ID)["output_revision"])
        loop_payload = store.load_review(_RUN_ID, _LOOP_ID)
        families = loop_payload.get("finding_families") or []
        assert families, "discovery should persist finding families on the loop"
        family_id = str(families[0]["id"])
        record_finding_actions(
            store,
            _RUN_ID,
            {
                "loop_id": _LOOP_ID,
                "target_revision": output_revision,
                "target_digest": digest_at_sweep,
                "finding_set_id": str(loop_payload.get("finding_set_id") or _FINDING_SET_ID),
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
            loop_id=_LOOP_ID,
        )()
        apply_production(
            store,
            _RUN_ID,
            {
                "goal_assessment": "Output goal is fully met after revision.",
            },
            handler="submit_completion",
            phase=WHOLE_OUTPUT_REVIEW,
        )()
        assert compute_output_digest(store.load_production(_RUN_ID)) == digest_at_sweep

    provider.script_turn(done_events(text="owner revision"), mutate_store=_producer_revision)

    def _verification_respond() -> None:
        loop_payload = store.load_review(_RUN_ID, _LOOP_ID)
        finding_set_id = str(loop_payload.get("finding_set_id") or _FINDING_SET_ID)
        target_revision = int(store.load_production(_RUN_ID)["output_revision"])
        respond_review(
            store,
            _RUN_ID,
            mandatory_verification_respond_request(
                store,
                _RUN_ID,
                loop_id=_LOOP_ID,
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
            loop_id=_LOOP_ID,
        )()

    provider.script_turn(
        done_events(text="verification complete"),
        mutate_store=_verification_respond,
    )

    def _scope_respond() -> None:
        target_revision = int(store.load_production(_RUN_ID)["output_revision"])
        respond_review(
            store,
            _RUN_ID,
            mandatory_scope_review_respond_request(
                store,
                _RUN_ID,
                loop_id=_LOOP_ID,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=_LOOP_ID,
        )()

    provider.script_turn(done_events(text="scope review complete"), mutate_store=_scope_respond)

    result = WholeOutputReviewOrchestrator(store, _RUN_ID, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    assert result.outcome == "accepted"
    review = store.load_review(_RUN_ID, _LOOP_ID)
    assert int(review["revision_cycles"]) == revision_cycles_before + 1
    assert review.get("verification_result")
    assert review.get("scope_review_result")
    owner_sweeps = [
        sweep
        for sweep in review.get("family_sweeps", [])
        if sweep.get("stage") == "owner_fix"
    ]
    assert owner_sweeps
    assert owner_sweeps[-1]["artifact_digest"] == compute_output_digest(
        store.load_production(_RUN_ID)
    )


def test_evidence_revision_apply_without_completion_still_clears_claim(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    _enter_owner_revision_in_progress(store, _RUN_ID)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    before = store.load_production(_RUN_ID)
    apply_production(
        store,
        _RUN_ID,
        _evidence_revision_request(
            production_revision=int(before["revision"]),
            with_completion=False,
        ),
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    production = store.load_production(_RUN_ID)
    assert production["completion_claim"] is None
    assert production["output_revision"] == int(before["output_revision"]) + 1
