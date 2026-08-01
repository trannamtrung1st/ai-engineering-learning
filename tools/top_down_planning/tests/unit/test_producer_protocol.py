"""Producer protocol guidance for production item contracts."""

from __future__ import annotations

from top_down_planning.orchestrator.producer_session import (
    build_producer_protocol_instructions,
)


def test_producer_protocol_requires_effective_scope_boundaries() -> None:
    protocol = " ".join(build_producer_protocol_instructions()).lower()
    assert "effective_scope" in protocol
    assert "effective_boundaries" in protocol
    assert "item-owned slice" in protocol
