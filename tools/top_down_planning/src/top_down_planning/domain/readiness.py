"""Dependency satisfaction, ready-set computation, and deadlock detection (proposal §7.3, §9.1–§9.2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from top_down_planning.domain.dependencies import (
    active_dependencies,
    dependency_cycle_issue,
    find_dependency_cycle,
)
from top_down_planning.domain.dispositions import DispositionMap
from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import active_children_of, is_active_item

SatisfactionState = Literal["satisfied", "unresolved", "blocked"]
SatisfactionSource = Literal["explicit", "derived_subtree", "none"]
ReadinessBlockReason = Literal[
    "unsatisfied_dependency",
    "review_blocked",
]
DeadlockCause = Literal[
    "cycle",
    "blocked_dependency",
    "missing_disposition",
    "unresolved_subtree",
    "review_blocked",
    "inconsistent_state",
]
ReviewBlockedFn = Callable[[str], bool]


@dataclass(frozen=True)
class SatisfactionResult:
    item_id: str
    state: SatisfactionState
    source: SatisfactionSource
    disposition: str | None = None
    blocker_item_id: str | None = None
    blocker_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "item_id": self.item_id,
            "state": self.state,
            "source": self.source,
        }
        if self.disposition is not None:
            payload["disposition"] = self.disposition
        if self.blocker_item_id is not None:
            payload["blocker_item_id"] = self.blocker_item_id
        if self.blocker_reason is not None:
            payload["blocker_reason"] = self.blocker_reason
        return payload


@dataclass(frozen=True)
class ReadinessBlocker:
    item_id: str
    reason: ReadinessBlockReason
    chain: list[str]
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "item_id": self.item_id,
            "reason": self.reason,
            "chain": list(self.chain),
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class ReadyView:
    ready_item_ids: list[str] = field(default_factory=list)
    not_ready: dict[str, ReadinessBlocker] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_item_ids": list(self.ready_item_ids),
            "not_ready": {
                item_id: blocker.to_dict() for item_id, blocker in self.not_ready.items()
            },
        }


@dataclass(frozen=True)
class DeadlockReport:
    cause: DeadlockCause
    waiting_item_ids: list[str]
    explanation: str
    blocking_chains: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "waiting_item_ids": list(self.waiting_item_ids),
            "explanation": self.explanation,
            "blocking_chains": {
                item_id: list(chain)
                for item_id, chain in self.blocking_chains.items()
            },
        }


def is_terminal_item(
    plan: Plan,
    item_id: str,
    dispositions: DispositionMap | None = None,
) -> bool:
    dispositions = dispositions or {}
    if item_id in dispositions:
        return True

    children = active_children_of(plan, item_id)
    if not children:
        return False

    return all(is_terminal_item(plan, child.id, dispositions) for child in children)


def is_applicable_item(
    plan: Plan,
    item_id: str,
    dispositions: DispositionMap | None = None,
) -> bool:
    dispositions = dispositions or {}
    item = plan.items.get(item_id)
    if item is None or not is_active_item(item):
        return False
    return not is_terminal_item(plan, item_id, dispositions)


def resolve_satisfaction(
    plan: Plan,
    item_id: str,
    dispositions: DispositionMap | None = None,
) -> SatisfactionResult:
    dispositions = dispositions or {}
    if item_id not in plan.items:
        return SatisfactionResult(
            item_id,
            "unresolved",
            "none",
            blocker_reason="unknown_item",
        )

    item = plan.items[item_id]
    if not is_active_item(item):
        return SatisfactionResult(item_id, "satisfied", "none")

    explicit = dispositions.get(item_id)
    if explicit is not None:
        if explicit == "blocked":
            return SatisfactionResult(
                item_id,
                "blocked",
                "explicit",
                disposition=explicit,
                blocker_item_id=item_id,
                blocker_reason="blocked_disposition",
            )
        return SatisfactionResult(
            item_id,
            "satisfied",
            "explicit",
            disposition=explicit,
        )

    children = active_children_of(plan, item_id)
    if not children:
        return SatisfactionResult(
            item_id,
            "unresolved",
            "none",
            blocker_item_id=item_id,
            blocker_reason="missing_disposition",
        )

    unresolved_children: list[SatisfactionResult] = []
    for child in children:
        child_result = resolve_satisfaction(plan, child.id, dispositions)
        if child_result.state != "satisfied":
            unresolved_children.append(child_result)

    if not unresolved_children:
        return SatisfactionResult(item_id, "satisfied", "derived_subtree")

    first = unresolved_children[0]
    blocker_item_id = first.blocker_item_id or first.item_id
    blocker_reason = first.blocker_reason or "unresolved_subtree"
    return SatisfactionResult(
        item_id,
        "unresolved",
        "derived_subtree",
        blocker_item_id=blocker_item_id,
        blocker_reason=blocker_reason,
    )


def is_dependency_satisfied(
    plan: Plan,
    dep_id: str,
    dispositions: DispositionMap | None = None,
) -> bool:
    return resolve_satisfaction(plan, dep_id, dispositions).state == "satisfied"


def readiness_blocker_for_item(
    plan: Plan,
    item_id: str,
    dispositions: DispositionMap | None = None,
    *,
    is_review_blocked: ReviewBlockedFn | None = None,
) -> ReadinessBlocker | None:
    dispositions = dispositions or {}
    is_review_blocked = is_review_blocked or (lambda _item_id: False)

    if not is_applicable_item(plan, item_id, dispositions):
        return None

    if is_review_blocked(item_id):
        return ReadinessBlocker(
            item_id,
            "review_blocked",
            [item_id],
            detail="blocked by unresolved review finding",
        )

    for dep_id in active_dependencies(plan, item_id):
        dep_result = resolve_satisfaction(plan, dep_id, dispositions)
        if dep_result.state != "satisfied":
            chain = [item_id, dep_id]
            blocker_item_id = dep_result.blocker_item_id or dep_id
            if blocker_item_id != dep_id:
                chain.append(blocker_item_id)
            detail = dep_result.blocker_reason or "unsatisfied_dependency"
            return ReadinessBlocker(
                item_id,
                "unsatisfied_dependency",
                chain,
                detail=detail,
            )

    return None


def compute_ready_view(
    plan: Plan,
    dispositions: DispositionMap | None = None,
    *,
    is_review_blocked: ReviewBlockedFn | None = None,
) -> ReadyView:
    dispositions = dispositions or {}
    view = ReadyView()

    for item_id, item in sorted(plan.items.items()):
        if not is_applicable_item(plan, item_id, dispositions):
            continue
        blocker = readiness_blocker_for_item(
            plan,
            item_id,
            dispositions,
            is_review_blocked=is_review_blocked,
        )
        if blocker is None:
            view.ready_item_ids.append(item_id)
        else:
            view.not_ready[item_id] = blocker

    return view


def _waiting_item_ids(plan: Plan, dispositions: DispositionMap) -> list[str]:
    return [
        item_id
        for item_id, item in sorted(plan.items.items())
        if is_applicable_item(plan, item_id, dispositions)
    ]


def _classify_deadlock_cause(
    plan: Plan,
    dispositions: DispositionMap,
    waiting_item_ids: list[str],
    *,
    is_review_blocked: ReviewBlockedFn,
) -> DeadlockCause:
    if find_dependency_cycle(plan) is not None:
        return "cycle"

    if any(is_review_blocked(item_id) for item_id in waiting_item_ids):
        return "review_blocked"

    for item_id in waiting_item_ids:
        for dep_id in active_dependencies(plan, item_id):
            dep_result = resolve_satisfaction(plan, dep_id, dispositions)
            if dep_result.state == "blocked":
                return "blocked_dependency"

    for item_id in waiting_item_ids:
        if not active_children_of(plan, item_id) and item_id not in dispositions:
            return "missing_disposition"

    for item_id in waiting_item_ids:
        if active_children_of(plan, item_id):
            result = resolve_satisfaction(plan, item_id, dispositions)
            if result.blocker_reason == "unresolved_subtree":
                return "unresolved_subtree"

    return "inconsistent_state"


def detect_deadlock(
    plan: Plan,
    dispositions: DispositionMap | None = None,
    *,
    is_review_blocked: ReviewBlockedFn | None = None,
) -> DeadlockReport | None:
    dispositions = dispositions or {}
    is_review_blocked = is_review_blocked or (lambda _item_id: False)
    ready_view = compute_ready_view(
        plan,
        dispositions,
        is_review_blocked=is_review_blocked,
    )
    waiting_item_ids = _waiting_item_ids(plan, dispositions)

    if not waiting_item_ids or ready_view.ready_item_ids:
        return None

    cause = _classify_deadlock_cause(
        plan,
        dispositions,
        waiting_item_ids,
        is_review_blocked=is_review_blocked,
    )
    blocking_chains = {
        item_id: blocker.chain
        for item_id, blocker in ready_view.not_ready.items()
        if item_id in waiting_item_ids
    }

    cycle_issue = dependency_cycle_issue(plan)
    if cause == "cycle" and cycle_issue is not None:
        explanation = (
            "All remaining applicable items are waiting and none are ready because "
            f"dependency cycle: {' -> '.join(cycle_issue.path)}"
        )
    elif cause == "review_blocked":
        explanation = (
            "All remaining applicable items are waiting and none are ready because "
            "at least one item is blocked by an unresolved review finding"
        )
    elif cause == "blocked_dependency":
        explanation = (
            "All remaining applicable items are waiting and none are ready because "
            "a required dependency has a blocked disposition"
        )
    elif cause == "missing_disposition":
        explanation = (
            "All remaining applicable items are waiting and none are ready because "
            "at least one leaf item lacks a terminal disposition"
        )
    elif cause == "unresolved_subtree":
        explanation = (
            "All remaining applicable items are waiting and none are ready because "
            "a non-leaf dependency has an unresolved applicable subtree"
        )
    else:
        explanation = (
            "All remaining applicable items are waiting and none are ready due to "
            "inconsistent dependency state"
        )

    return DeadlockReport(
        cause=cause,
        waiting_item_ids=waiting_item_ids,
        explanation=explanation,
        blocking_chains=blocking_chains,
    )
