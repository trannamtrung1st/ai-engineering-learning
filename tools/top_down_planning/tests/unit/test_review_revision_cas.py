"""Review-loop record revision CAS tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import StoreRevisionConflictError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.review_commit import (
    review_record_revision,
    save_review_with_expected_revision,
)
from tests.helpers import create_run_kwargs, make_review_loop


def _sample_plan() -> Plan:
    return Plan(
        id="plan-review-rev",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def _create_run(store: FileRunStore, run_id: str) -> None:
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root),
    )


def test_save_review_with_expected_revision_bumps_record(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007001-007001"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="loop-rev-01",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

    next_revision = save_review_with_expected_revision(
        store,
        run_id,
        loop,
        expected_revision=0,
    )
    assert next_revision == 1
    loaded = store.load_review(run_id, loop.id)
    assert review_record_revision(loaded) == 1


def test_save_review_with_expected_revision_rejects_stale_write(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T007002-007002"
    _create_run(store, run_id)
    loop = make_review_loop(
        id="loop-rev-02",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

    with pytest.raises(StoreRevisionConflictError):
        save_review_with_expected_revision(
            store,
            run_id,
            loop,
            expected_revision=1,
        )


def test_record_finding_actions_bumps_review_record_revision(tmp_path: Path) -> None:
    from top_down_planning.domain.finding_families import compute_family_fingerprint
    from top_down_planning.agent_tool import ReviewAgentService
    from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
    from tests.helpers import grant_capability, mandatory_output_digest
    from tests.unit.test_whole_output_review import _create_run_at_whole_output_review

    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    run_id = "run-20260101T000801-000801"
    loop_id = "review-whole-output-01"
    loop_payload = dict(store.load_review(run_id, loop_id))
    loop_payload["target_revision"] = 0
    loop_payload["finding_set_id"] = "review-whole-output-01-fs-01"
    loop_payload["finding_families"] = [
        {
            "id": "family-output-01",
            "finding_set_id": "review-whole-output-01-fs-01",
            "rule_id": "custom.evidence-gap",
            "subject_key": "leaf-evidence",
            "scope_kind": "whole-output",
            "rule_definition": "output evidence completeness gap",
            "family_fingerprint": compute_family_fingerprint(
                rule_id="custom.evidence-gap",
                subject_key="leaf-evidence",
                scope_kind="whole-output",
                rule_definition="output evidence completeness gap",
            ),
            "title": "Evidence gap",
            "seed_finding_id": "finding-01",
            "confirmed_finding_ids": ["finding-01"],
            "candidate_refs": [],
            "recommended_change": "Add artifact reference.",
        }
    ]
    loop_payload["findings"] = [
        {
            "id": "finding-01",
            "severity": "blocker",
            "category": "traceability",
            "target_refs": ["item-leaf"],
            "issue": "Missing evidence.",
            "recommended_change": "Add artifact reference.",
            "family_id": "family-output-01",
        }
    ]
    loop_payload["finding_ids_by_set"] = {
        "review-whole-output-01-fs-01": ["finding-01"]
    }
    store.save_review(run_id, loop_payload)

    revision = int(store.load_production(run_id)["output_revision"])
    digest = mandatory_output_digest(store, run_id)
    token = grant_capability(
        store,
        run_id,
        role="producer",
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id=loop_id,
    )
    ReviewAgentService(store, run_id).record_finding_actions(
        {
            "loop_id": loop_id,
            "target_revision": revision,
            "target_digest": digest,
            "finding_set_id": "review-whole-output-01-fs-01",
            "family_fixes": [
                {
                    "family_id": "family-output-01",
                    "target_finding_ids": [],
                    "rationale": "fixed",
                    "changed_refs": ["item-leaf"],
                    "owner_sweep": {
                        "searched_refs": ["production:*"],
                        "search_dimensions": ["evidence"],
                        "additional_fixed_refs": [],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "done",
                    },
                }
            ],
            "finding_actions": [],
        },
        capability_token=token,
    )

    loaded = store.load_review(run_id, loop_id)
    assert review_record_revision(loaded) == 1
