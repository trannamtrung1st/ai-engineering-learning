"""Planner protocol guidance for plan field classification."""

from __future__ import annotations

from top_down_planning.orchestrator.planner_session import (
    build_planner_protocol_instructions,
    build_planner_tool_instructions,
)


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


def test_planner_protocol_requires_work_leaf_scope_contract() -> None:
    protocol = " ".join(build_planner_protocol_instructions()).lower()
    assert "every work leaf must set item-level scope.includes" in protocol


def test_planner_protocol_requires_populating_seeded_root() -> None:
    protocol = " ".join(build_planner_protocol_instructions()).lower()
    assert "item-root" in protocol
    assert "update_item" in protocol
    assert "update_plan" in protocol


def test_planner_protocol_includes_family_repair_guidance() -> None:
    protocol = " ".join(build_planner_protocol_instructions()).lower()
    assert "active_families" in protocol
    assert "repair unit" in protocol
    assert "target_finding_ids" in protocol
    assert "remaining_instance_refs" in protocol
    assert "seed finding" in protocol


def test_planner_protocol_documents_inline_depends_on() -> None:
    protocol = " ".join(build_planner_protocol_instructions()).lower()
    assert "depends_on" in protocol
    assert "expand-branch" in protocol


def test_planner_tool_instructions_include_discover_and_depends_on() -> None:
    instructions = build_planner_tool_instructions("run-test")
    assert "discover" in instructions
    assert "expand-branch" in instructions["discover"]
    assert "plan_depends_on" in instructions
    assert "temp_id" in instructions["plan_depends_on"].lower()
