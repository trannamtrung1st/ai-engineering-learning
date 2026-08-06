"""Plan and plan-item models (proposal §7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from top_down_planning.domain.plan_schema import (
    PLAN_SCHEMA_VERSION,
    normalize_plan_item_payload,
    normalize_plan_payload,
)

PlanningStatus = Literal["open", "superseded", "removed"]
ItemKind = Literal["aggregate", "work"]


@dataclass
class Scope:
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {"includes": list(self.includes), "excludes": list(self.excludes)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Scope:
        from top_down_planning.domain.plan_schema import require_scope_dict

        normalized = require_scope_dict(data, field_label="scope")
        return cls(
            includes=list(normalized["includes"]),
            excludes=list(normalized["excludes"]),
        )


@dataclass
class PlanItem:
    id: str
    parent_id: str | None
    order_key: str
    title: str
    kind: ItemKind
    outcome: str = ""
    scope: Scope = field(default_factory=Scope)
    boundaries: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    planning_status: PlanningStatus = "open"
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "parent_id": self.parent_id,
            "order_key": self.order_key,
            "title": self.title,
            "outcome": self.outcome,
            "scope": self.scope.to_dict(),
            "boundaries": list(self.boundaries),
            "depends_on": list(self.depends_on),
            "acceptance": list(self.acceptance),
            "risks": list(self.risks),
            "source_refs": list(self.source_refs),
            "planning_status": self.planning_status,
            "kind": self.kind,
        }
        if self.superseded_by is not None:
            payload["superseded_by"] = self.superseded_by
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanItem:
        normalized = normalize_plan_item_payload(data)
        return cls(
            id=normalized["id"],
            parent_id=normalized["parent_id"],
            order_key=normalized["order_key"],
            title=normalized["title"],
            outcome=normalized["outcome"],
            scope=Scope.from_dict(normalized["scope"]),
            boundaries=list(normalized["boundaries"]),
            depends_on=list(normalized["depends_on"]),
            acceptance=list(normalized["acceptance"]),
            risks=list(normalized["risks"]),
            source_refs=list(normalized["source_refs"]),
            planning_status=normalized["planning_status"],  # type: ignore[arg-type]
            superseded_by=normalized["superseded_by"],
            kind=normalized["kind"],  # type: ignore[arg-type]
        )


@dataclass
class Plan:
    id: str
    revision: int
    output_goal: str
    items: dict[str, PlanItem] = field(default_factory=dict)
    input_refs: list[str] = field(default_factory=list)
    scope: Scope = field(default_factory=Scope)
    boundaries: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    schema_version: int = PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        from top_down_planning.domain.plan_tree import serialized_plan_items

        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "revision": self.revision,
            "input_refs": list(self.input_refs),
            "output_goal": self.output_goal,
            "scope": self.scope.to_dict(),
            "boundaries": list(self.boundaries),
            "constraints": list(self.constraints),
            "assumptions": list(self.assumptions),
            "acceptance": list(self.acceptance),
            "risks": list(self.risks),
            "items": serialized_plan_items(self),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        from top_down_planning.domain.plan_tree import validate_persisted_item_depths

        normalized = normalize_plan_payload(data)
        schema_version = normalized["schema_version"]

        items_list = normalized["items"]
        items: dict[str, PlanItem] = {}
        for raw_item in items_list:
            if not isinstance(raw_item, dict):
                raise ValueError("each plan item must be an object")
            item = PlanItem.from_dict(raw_item)
            if item.id in items:
                raise ValueError(f"duplicate plan item id: {item.id}")
            items[item.id] = item
        plan = cls(
            id=normalized["id"],
            revision=normalized["revision"],
            output_goal=normalized["output_goal"],
            items=items,
            input_refs=list(normalized.get("input_refs") or []),
            scope=Scope.from_dict(normalized.get("scope")),
            boundaries=list(normalized.get("boundaries") or []),
            constraints=list(normalized.get("constraints") or []),
            assumptions=list(normalized.get("assumptions") or []),
            acceptance=list(normalized.get("acceptance") or []),
            risks=list(normalized.get("risks") or []),
            schema_version=schema_version,
        )
        validate_persisted_item_depths(plan, items_list)
        return plan


@dataclass
class PlanningLimits:
    """Soft planning limits with package defaults."""

    max_depth: int = 4
    max_expansion_per_item: int = 7


@dataclass
class PlanningBudget:
    item_id: str
    depth: int
    max_depth: int
    depth_remaining: int
    direct_children: int
    max_expansion_per_item: int
    expansion_remaining: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "depth": self.depth,
            "max_depth": self.max_depth,
            "depth_remaining": self.depth_remaining,
            "direct_children": self.direct_children,
            "max_expansion_per_item": self.max_expansion_per_item,
            "expansion_remaining": self.expansion_remaining,
            "warnings": list(self.warnings),
        }


@dataclass
class ApplyResult:
    plan: Plan
    revision: int
    id_map: dict[str, str] = field(default_factory=dict)
    changed_item_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    budgets: list[PlanningBudget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "id_map": dict(self.id_map),
            "changed_item_ids": list(self.changed_item_ids),
            "warnings": list(self.warnings),
            "budgets": [budget.to_dict() for budget in self.budgets],
        }
