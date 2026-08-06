"""Hard-cutover tests for mandatory whole-plan and whole-output contract v2 (SoT §14)."""

from __future__ import annotations

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
