"""Hard-cutover tests for mandatory whole-plan and whole-output contract v2 (SoT §14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.orchestrator import WholeOutputReviewOrchestrator, WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import grant_capability, mandatory_output_digest, save_review_payload
from tests.unit.test_whole_output_review import _create_run_at_whole_output_review
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review


def test_nonterminal_whole_plan_v1_loop_rejects_before_provider(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"

    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-plan-01",
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
            "review_contract_version": 1,
        },
    )

    with pytest.raises(ProviderRunError, match="contract v2"):
        WholePlanReviewOrchestrator(store, run_id, provider).run()


def test_nonterminal_whole_output_v1_loop_rejects_before_provider(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"

    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 1,
        },
    )

    with pytest.raises(ProviderRunError, match="contract v2"):
        WholeOutputReviewOrchestrator(store, run_id, provider).run()


def test_mandatory_whole_output_v1_respond_rejected(tmp_path: Path) -> None:
    from top_down_planning.agent_tool import ReviewAgentService
    from top_down_planning.agent_tool.errors import RequestError

    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    run_id = "run-20260101T000801-000801"
    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 1,
        },
    )
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_OUTPUT_REVIEW,
        session_id="stub-reviewer",
        loop_id="review-whole-output-01",
    )
    service = ReviewAgentService(store, run_id)
    with pytest.raises(RequestError, match="contract v2"):
        service.respond(
            {
                "loop_id": "review-whole-output-01",
                "target_revision": 1,
                "stage": "initial_review",
                "finding_set_id": "review-whole-output-01-fs-01",
                "reported_findings": [],
                "review_completed": True,
                "target_digest": mandatory_output_digest(store, run_id),
                "summary": "clear",
            },
            capability_token=token,
        )


def test_completed_v1_whole_output_record_remains_parseable(tmp_path: Path) -> None:
    from top_down_planning.domain.reviews import ReviewLoop

    loop = ReviewLoop.from_dict(
        {
            "id": "review-whole-output-legacy",
            "type": "whole_output",
            "target_revision": 0,
            "scope": {"kind": "whole_output"},
            "status": "approved",
            "lifecycle_status": "approved",
            "revise_at": "blocker",
            "findings": [],
            "revision_cycles": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 1,
        }
    )
    assert loop.review_contract_version == 1
    assert loop.status == "approved"
