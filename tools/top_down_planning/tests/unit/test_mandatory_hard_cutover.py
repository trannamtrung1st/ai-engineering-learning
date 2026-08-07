"""Hard-cutover tests for mandatory whole-plan and whole-output contract v2 (SoT §14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.reviews import ReviewLoop, UnsupportedReviewSchemaVersionError


def test_whole_plan_v1_contract_payload_rejected_on_load() -> None:
    with pytest.raises(UnsupportedReviewSchemaVersionError, match="recreate the run"):
        ReviewLoop.from_dict(
            {
                "id": "review-whole-plan-01",
                "type": "whole_plan",
                "revise_at": "blocker",
                "target_revision": 0,
                "scope": {"kind": "whole_plan"},
                "status": "pending",
                "findings": [],
                "finding_actions": [],
                "revision_cycles": 0,
                "revision": 0,
                "lifecycle_status": "review_pending",
                "scope_review_rounds": 0,
                "review_record_schema_version": 2,
                "review_contract_version": 1,
            }
        )


def test_whole_output_v1_contract_payload_rejected_on_load() -> None:
    with pytest.raises(UnsupportedReviewSchemaVersionError, match="recreate the run"):
        ReviewLoop.from_dict(
            {
                "id": "review-whole-output-01",
                "type": "whole_output",
                "revise_at": "blocker",
                "target_revision": 1,
                "scope": {"kind": "whole_output"},
                "status": "pending",
                "findings": [],
                "finding_actions": [],
                "revision_cycles": 0,
                "revision": 0,
                "lifecycle_status": "review_pending",
                "scope_review_rounds": 0,
                "review_record_schema_version": 2,
                "review_contract_version": 1,
            }
        )


def test_whole_output_v1_record_schema_rejected_on_load() -> None:
    with pytest.raises(UnsupportedReviewSchemaVersionError, match="recreate the run"):
        ReviewLoop.from_dict(
            {
                "id": "review-whole-output-legacy",
                "type": "whole_output",
                "target_revision": 0,
                "scope": {"kind": "whole_output"},
                "status": "approved",
                "lifecycle_status": "approved",
                "revise_at": "blocker",
                "findings": [],
                "finding_actions": [],
                "revision_cycles": 0,
                "revision": 0,
                "review_record_schema_version": 1,
                "review_contract_version": 1,
            }
        )


def test_approval_record_helpers_include_mandatory_v2_version_fields(
    tmp_path: Path,
) -> None:
    from top_down_planning.domain.models import Plan
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item
    from top_down_planning.persistence import FileRunStore
    from tests.helpers import (
        MANDATORY_REVIEW_V2_VERSION_FIELDS,
        create_run_kwargs,
        whole_output_approval_record,
        whole_plan_approval_record,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: seed_plan_root_item()},
    )
    production = {
        "revision": 1,
        "output_revision": 1,
        "batches": [],
        "outputs": [],
        "contributions": [],
        "dispositions": {},
        "output_evidence": [],
    }
    store.create_run(
        run_id,
        plan=plan,
        production=production,
        **create_run_kwargs(tmp_path),
    )

    for helper in (whole_plan_approval_record, whole_output_approval_record):
        payload = helper(store, run_id)
        for field_name, expected in MANDATORY_REVIEW_V2_VERSION_FIELDS.items():
            assert payload[field_name] == expected
            assert type(payload[field_name]) is int
        ReviewLoop.from_dict(payload)
