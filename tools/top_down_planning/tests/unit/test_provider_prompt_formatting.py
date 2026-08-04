"""Provider prompt formatting for rendered protocol strings."""

from __future__ import annotations

from core_tools.provider.events import format_manifest_prompt, format_request_prompt

from top_down_planning.orchestrator.planner_session import build_planner_protocol_instructions
from top_down_planning.orchestrator.producer_session import build_producer_protocol_instructions
from top_down_planning.orchestrator.reviewer_session import build_reviewer_protocol_instructions


def test_planner_manifest_protocol_formats_for_provider() -> None:
    protocol = build_planner_protocol_instructions()
    prompt = format_manifest_prompt(
        "planner",
        {
            "phase": "planning",
            "protocol_instructions": protocol,
        },
    )

    assert prompt.startswith("Role: planner\n\nProtocol:\n")
    assert protocol in prompt
    assert "\nContext manifest:\n" in prompt


def test_producer_manifest_protocol_formats_for_provider() -> None:
    protocol = build_producer_protocol_instructions()
    prompt = format_manifest_prompt(
        "producer",
        {
            "phase": "production",
            "protocol_instructions": protocol,
        },
    )

    assert prompt.startswith("Role: producer\n\nProtocol:\n")
    assert protocol in prompt
    assert "TDP_CAPABILITY_TOKEN_FILE" in prompt


def test_reviewer_request_protocol_formats_for_provider() -> None:
    protocol = build_reviewer_protocol_instructions(
        stage="initial_review",
        review_type="whole_plan",
    )
    prompt = format_request_prompt(
        {
            "phase": "whole_plan_review",
            "agent_context": {"role": "reviewer"},
            "protocol_instructions": protocol,
        },
    )

    assert prompt.startswith("Role: reviewer\n\nProtocol:\n")
    assert protocol in prompt
    assert "complete gap-seeking sweep produces no additional" in prompt
    assert "\nRequest:\n" in prompt
