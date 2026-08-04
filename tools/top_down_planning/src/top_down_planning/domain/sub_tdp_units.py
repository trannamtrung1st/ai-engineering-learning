"""Derive Sub-TDP units from approved parent plan root subtrees."""

from __future__ import annotations

import re
from dataclasses import dataclass

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, active_children_of


@dataclass(frozen=True)
class SubTdpUnit:
    plan_item_id: str
    title: str
    outcome: str
    directory: str
    ordinal: int

    @property
    def id(self) -> str:
        return self.plan_item_id


_slug_pattern = re.compile(r"[^a-z0-9]+")


def slug_from_title(title: str) -> str:
    lowered = title.strip().lower()
    slug = _slug_pattern.sub("-", lowered).strip("-")
    return slug or "unit"


def derive_sub_tdp_units(plan: Plan) -> list[SubTdpUnit]:
    """Each direct active child of the plan root is one Sub-TDP unit."""

    children = active_children_of(plan, PLAN_ROOT_ITEM_ID)
    if not children:
        raise ValueError("approved plan has no active root children for Sub-TDP decomposition")

    units: list[SubTdpUnit] = []
    for index, item in enumerate(children, start=1):
        slug = slug_from_title(item.title)
        directory = f"{index:02d}-{slug}"
        units.append(
            SubTdpUnit(
                plan_item_id=item.id,
                title=item.title,
                outcome=item.outcome,
                directory=directory,
                ordinal=index,
            )
        )
    return units


__all__ = ["SubTdpUnit", "derive_sub_tdp_units", "slug_from_title"]
