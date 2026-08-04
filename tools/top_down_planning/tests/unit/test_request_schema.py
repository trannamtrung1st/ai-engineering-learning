"""Agent request payload validation against published CLI schemas."""

from __future__ import annotations

import pytest

from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.agent_tool.request_schema import validate_agent_request
from top_down_planning.schema_docs import show_example, validate_example


def test_validate_agent_request_accepts_plan_apply_example() -> None:
    payload = show_example("expand-branch")["payload"]
    validate_agent_request("plan_apply", payload)


def test_validate_agent_request_rejects_missing_base_revision() -> None:
    with pytest.raises(RequestError, match="base_revision"):
        validate_agent_request("plan_apply", {"operations": []})


def test_validate_agent_request_rejects_extra_production_apply_fields() -> None:
    payload = dict(show_example("batch-result")["payload"])
    payload["batch_id"] = "custom-batch"
    with pytest.raises(RequestError, match="unexpected properties"):
        validate_agent_request("production_apply", payload)


def test_validate_agent_request_accepts_lean_completion_claim() -> None:
    payload = show_example("completion-claim")["payload"]
    validate_agent_request("production_submit_completion", payload)


def test_validate_agent_request_rejects_completion_claim_goal_met() -> None:
    payload = {
        "goal_assessment": "Done.",
        "goal_met": True,
    }
    with pytest.raises(RequestError, match="unexpected properties"):
        validate_agent_request("production_submit_completion", payload)


def test_validate_agent_request_accepts_focused_review_request_without_scope_kind() -> None:
    payload = {
        "type": "focused_plan",
        "scope": {"item_ids": ["item-api"]},
    }
    validate_agent_request("review_request", payload)


def test_validate_agent_request_accepts_lean_record_actions_example() -> None:
    payload = show_example("review-record-finding-actions")["payload"]
    validate_agent_request("review_record_finding_actions", payload)


def test_validate_agent_request_structured_path_on_nested_failure() -> None:
    with pytest.raises(RequestError, match=r"\$\.operations\[0\]"):
        validate_agent_request(
            "plan_apply",
            {
                "base_revision": 0,
                "operations": [{"op": "unknown_op"}],
            },
        )


def test_all_public_examples_validate_against_schemas() -> None:
  for name in (
        "expand-branch",
        "batch-result",
        "empty-output",
        "evidence-revision",
        "evidence-revision-focused",
        "review-respond",
        "review-respond-focused-with-instance-ref",
        "review-respond-family-discovery-focused-plan",
        "review-respond-family-discovery-focused-output",
        "review-respond-verification",
        "review-respond-scope",
        "review-respond-family-discovery",
        "review-respond-family-discovery-output",
        "review-respond-family-verification",
        "review-respond-family-verification-output",
        "review-record-family-fix",
        "review-record-family-fix-output",
        "review-record-finding-actions",
        "focused-review-request",
        "amendment-request",
        "completion-claim",
        "blocker-report",
    ):
        issues = validate_example(name)
        assert issues == [], f"{name}: {issues}"
