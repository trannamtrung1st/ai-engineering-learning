"""Producer session tool instruction coverage."""

from __future__ import annotations

from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR
from top_down_planning.orchestrator.producer_session import (
    build_producer_protocol_instructions,
    build_producer_tool_instructions,
)


def test_producer_protocol_points_to_injected_skills() -> None:
    protocol = build_producer_protocol_instructions().lower()
    assert "agent_context.skills" in protocol
    assert "one production batch per provider turn" in protocol
    assert "submit-completion" in protocol
    assert "completion claim" in protocol
    assert CAPABILITY_TOKEN_FILE_ENV_VAR.lower() in protocol
    assert "production_evidence_incomplete" in protocol
    assert "production_context_mutation_unauthorized" in protocol
    assert "$tdp_agent_requests_dir" in protocol


def test_producer_tool_instructions_include_discover() -> None:
    instructions = build_producer_tool_instructions("run-test")
    assert "discover" in instructions
    assert "batch-result" in instructions["discover"]
    assert "production-apply" in instructions["discover"]
