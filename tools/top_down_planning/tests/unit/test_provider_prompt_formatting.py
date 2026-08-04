"""Provider prompt formatting for rendered protocol strings."""

from __future__ import annotations

from core_tools.provider.events import format_manifest_prompt

from top_down_planning.orchestrator.planner_session import build_planner_protocol_instructions


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
