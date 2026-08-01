"""Planner protocol guidance for plan field classification."""

from __future__ import annotations

from top_down_planning.orchestrator.planner_session import build_planner_protocol_instructions


def test_planner_protocol_includes_classification_guide() -> None:
    protocol = " ".join(build_planner_protocol_instructions()).lower()
    assert "acceptance" in protocol
    assert "risks" in protocol
    assert "source_refs" in protocol
    assert "scope.includes" in protocol


def test_planner_protocol_discourages_risks_in_acceptance_and_scope_refs() -> None:
    protocol = " ".join(build_planner_protocol_instructions()).lower()
    assert "do not place architecture suggestions in acceptance" in protocol
    assert "do not convert every possible defect into a risk" in protocol
    assert "do not place source-document section names in scope.includes" in protocol
