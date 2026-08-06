"""Contract fields on review packages."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import ReviewLoop, UnsupportedReviewSchemaVersionError
from top_down_planning.orchestrator.review_analysis_context import contract_fields
from tests.helpers import make_review_loop


def test_family_protocol_enabled_follows_contract_version() -> None:
    v2_loop = make_review_loop(
        id="review-whole-plan-v2",
        type="whole_plan",
        reviewer_session_id="sess",
        review_contract_version=2,
    )
    assert contract_fields(v2_loop)["family_protocol_enabled"] is True
    with pytest.raises(UnsupportedReviewSchemaVersionError, match="recreate the run"):
        ReviewLoop.from_dict(
            {
                "id": "review-whole-plan-v1",
                "type": "whole_plan",
                "target_revision": 0,
                "scope": {"kind": "whole_plan"},
                "status": "pending",
                "revise_at": "blocker",
                "findings": [],
                "finding_actions": [],
                "revision_cycles": 0,
                "revision": 0,
                "review_record_schema_version": 2,
                "review_contract_version": 1,
            }
        )
