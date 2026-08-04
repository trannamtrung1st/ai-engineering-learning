"""Contract fields on review packages."""

from __future__ import annotations

from top_down_planning.orchestrator.review_analysis_context import contract_fields
from tests.helpers import make_review_loop


def test_family_protocol_enabled_follows_contract_version() -> None:
    v2_loop = make_review_loop(
        id="review-whole-plan-v2",
        type="whole_plan",
        reviewer_session_id="sess",
        review_contract_version=2,
    )
    v1_loop = make_review_loop(
        id="review-whole-plan-v1",
        type="whole_plan",
        reviewer_session_id="sess",
        review_contract_version=1,
    )
    assert contract_fields(v2_loop)["family_protocol_enabled"] is True
    assert contract_fields(v1_loop)["family_protocol_enabled"] is False
