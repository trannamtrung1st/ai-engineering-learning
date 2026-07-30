"""Plan and plan-item models (proposal §7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PlanningStatus = Literal["open", "superseded", "removed"]


PLAN_SCHEMA_VERSION = 1


@dataclass
class Scope:
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {"includes": list(self.includes), "excludes": list(self.excludes)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Scope:
        if not data:
            return cls()
        return cls(
            includes=list(data.get("includes") or []),
            excludes=list(data.get("excludes") or []),
        )


@dataclass
class PlanItem:
    id: str
    parent_id: str | None
    order_key: str
    title: str
    outcome: str = ""
    scope: Scope = field(default_factory=Scope)
    boundaries: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
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
            "planning_status": self.planning_status,
        }
        if self.superseded_by is not None:
            payload["superseded_by"] = self.superseded_by
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanItem:
        return cls(
            id=data["id"],
            parent_id=data.get("parent_id"),
            order_key=data["order_key"],
            title=data["title"],
            outcome=data.get("outcome", ""),
            scope=Scope.from_dict(data.get("scope")),
            boundaries=list(data.get("boundaries") or []),
            depends_on=list(data.get("depends_on") or []),
            acceptance=list(data.get("acceptance") or []),
            planning_status=data.get("planning_status", "open"),
            superseded_by=data.get("superseded_by"),
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
            "items": serialized_plan_items(self),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        if "schema_version" not in data:
            raise ValueError("plan schema_version is required")

        items_list = data.get("items") or []
        items: dict[str, PlanItem] = {}
        for raw_item in items_list:
            if not isinstance(raw_item, dict):
                raise ValueError("each plan item must be an object")
            item = PlanItem.from_dict(raw_item)
            if item.id in items:
                raise ValueError(f"duplicate plan item id: {item.id}")
            items[item.id] = item
        return cls(
            id=data["id"],
            revision=int(data.get("revision", 0)),
            output_goal=data.get("output_goal", ""),
            items=items,
            input_refs=list(data.get("input_refs") or []),
            scope=Scope.from_dict(data.get("scope")),
            boundaries=list(data.get("boundaries") or []),
            constraints=list(data.get("constraints") or []),
            assumptions=list(data.get("assumptions") or []),
            acceptance=list(data.get("acceptance") or []),
            schema_version=int(data["schema_version"]),
        )


@dataclass
class PlanningLimits:
    """Soft planning limits; defaults match ``config.defaults.DEFAULT_CONFIG.planning``."""

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
