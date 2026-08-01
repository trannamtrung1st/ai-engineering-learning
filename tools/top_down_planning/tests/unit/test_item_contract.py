"""Tests for item production contracts and scope merge."""

from __future__ import annotations

from top_down_planning.domain.item_contract import (
    build_item_production_contract,
    effective_boundaries,
    effective_scope,
    has_item_scope_contract,
    merge_string_lists,
)
from top_down_planning.domain.models import Plan, PlanItem, Scope


def _plan_with_item(item: PlanItem, *, plan_scope: Scope | None = None) -> Plan:
    plan = Plan(
        id="plan-contract",
        revision=1,
        output_goal="Deliver.",
        scope=plan_scope or Scope(includes=["plan-include"], excludes=["plan-exclude"]),
        boundaries=["plan-boundary"],
        items={item.id: item},
    )
    return plan


def test_merge_string_lists_skips_blanks_and_dedupes_casefold() -> None:
    merged = merge_string_lists(
        [" Alpha ", "", "beta"],
        ["alpha", "Gamma", "beta"],
    )
    assert merged == ["Alpha", "beta", "Gamma"]


def test_effective_scope_merges_plan_and_item() -> None:
    item = PlanItem(
        id="item-work",
        parent_id=None,
        order_key="0000000000",
        title="Work",
        kind="work",
        scope=Scope(includes=["item-include"], excludes=["item-exclude"]),
    )
    plan = _plan_with_item(item)
    resolved = effective_scope(plan, item)
    assert resolved.includes == ["plan-include", "item-include"]
    assert resolved.excludes == ["plan-exclude", "item-exclude"]


def test_effective_scope_includes_plan_level_guardrails() -> None:
    """Merge helper unions plan-level guardrails with item-owned scope."""
    item = PlanItem(
        id="item-work",
        parent_id=None,
        order_key="0000000000",
        title="Work",
        kind="work",
    )
    plan = _plan_with_item(item)
    resolved = effective_scope(plan, item)
    assert resolved.includes == ["plan-include"]
    assert resolved.excludes == ["plan-exclude"]


def test_effective_boundaries_merges_plan_and_item() -> None:
    item = PlanItem(
        id="item-work",
        parent_id=None,
        order_key="0000000000",
        title="Work",
        kind="work",
        boundaries=["item-boundary"],
    )
    plan = _plan_with_item(item)
    assert effective_boundaries(plan, item) == ["plan-boundary", "item-boundary"]


def test_has_item_scope_contract_requires_non_blank_entries() -> None:
    item = PlanItem(
        id="item-work",
        parent_id=None,
        order_key="0000000000",
        title="Work",
        kind="work",
        scope=Scope(includes=["   "]),
    )
    assert not has_item_scope_contract(item)
    item.scope = Scope(includes=["owned capability"])
    assert has_item_scope_contract(item)


def test_build_item_production_contract_shape() -> None:
    item = PlanItem(
        id="item-work",
        parent_id=None,
        order_key="0000000000",
        title="Work",
        outcome="Work outcome.",
        kind="work",
        scope=Scope(includes=["owned capability"]),
        boundaries=["No external APIs"],
        acceptance=["Works"],
        risks=["Risk"],
        source_refs=["spec.md → Section"],
        depends_on=["item-other"],
    )
    plan = _plan_with_item(item)
    contract = build_item_production_contract(plan, "item-work")
    assert contract["id"] == "item-work"
    assert contract["scope"] == {"includes": ["owned capability"], "excludes": []}
    assert contract["boundaries"] == ["No external APIs"]
    assert contract["effective_scope"]["includes"] == ["plan-include", "owned capability"]
    assert contract["effective_boundaries"] == ["plan-boundary", "No external APIs"]
    assert contract["acceptance"] == ["Works"]
    assert contract["risks"] == ["Risk"]
    assert contract["source_refs"] == ["spec.md → Section"]
    assert contract["depends_on"] == ["item-other"]
    assert "ancestor_path" not in contract
