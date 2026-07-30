"""Deterministic plan validation (proposal §6.2–§6.3, §9, §12.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from top_down_planning.domain.dependencies import dependency_cycle_issue
from top_down_planning.domain.dispositions import DispositionMap, SATISFIED_DISPOSITIONS
from top_down_planning.domain.models import Plan, PlanningLimits, PLAN_SCHEMA_VERSION
from top_down_planning.domain.plan_tree import (
    compute_planning_budget,
    find_hierarchy_cycle,
    is_active_item,
    walk_active_tree,
)
from top_down_planning.domain.readiness import ReviewBlockedFn, detect_deadlock, resolve_satisfaction
from top_down_planning.domain.reviews import build_is_review_blocked_fn

ValidationSeverity = Literal["error", "warning"]
ValidationMode = Literal["draft", "approval"]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    message: str
    path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.path:
            payload["path"] = list(self.path)
        return payload


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class ReviewState:
    """Optional whole-plan review context for approval-mode hooks."""

    approved_revision: int | None = None
    unresolved_blocking_findings: list[str] = field(default_factory=list)


@dataclass
class DigestBundle:
    """Optional digest bindings for approval-mode hooks."""

    plan_revision: int | None = None
    expected_plan_digest: str | None = None
    actual_plan_digest: str | None = None
    input_digest: str | None = None
    expected_input_digest: str | None = None
    output_goal_digest: str | None = None
    expected_output_goal_digest: str | None = None
    config_digest: str | None = None
    expected_config_digest: str | None = None
    context_digest: str | None = None
    expected_context_digest: str | None = None


def build_plan_approval_validation_context(
    *,
    run: dict[str, Any],
    plan: Plan,
    approval: dict[str, Any],
    actual_plan_digest: str,
    actual_config_digest: str,
) -> tuple[ReviewState, DigestBundle]:
    """Build approval-mode review and digest bindings for the current plan revision."""

    from top_down_planning.domain.reviews import blocking_unresolved_finding_ids_from_payload

    digests = run.get("digests") or {}
    review_state = ReviewState(
        approved_revision=int(approval["target_revision"]),
        unresolved_blocking_findings=blocking_unresolved_finding_ids_from_payload(
            approval
        ),
    )
    digest_bundle = DigestBundle(
        plan_revision=plan.revision,
        expected_plan_digest=digests.get("plan"),
        actual_plan_digest=actual_plan_digest,
        input_digest=digests.get("input"),
        expected_input_digest=digests.get("input"),
        output_goal_digest=digests.get("output_goal"),
        expected_output_goal_digest=digests.get("output_goal"),
        config_digest=actual_config_digest,
        expected_config_digest=digests.get("config"),
        context_digest=digests.get("context"),
        expected_context_digest=digests.get("context"),
    )
    return review_state, digest_bundle


def _issue(
    code: str,
    severity: ValidationSeverity,
    message: str,
    path: list[str] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        path=list(path or []),
    )


def validation_issue(
    code: str,
    severity: ValidationSeverity,
    message: str,
    path: list[str] | None = None,
) -> ValidationIssue:
    """Public helper for constructing validation issues from sibling modules."""

    return _issue(code, severity, message, path)


def _severity_for_mode(mode: ValidationMode, draft_severity: ValidationSeverity) -> ValidationSeverity:
    if mode == "approval" and draft_severity == "warning":
        return "error"
    return draft_severity


def _normalized_cycle_key(cycle: list[str]) -> tuple[str, ...]:
    if len(cycle) < 2:
        return tuple(cycle)
    body = cycle[:-1] if cycle[-1] == cycle[0] else list(cycle)
    if not body:
        return tuple(cycle)
    start = min(range(len(body)), key=lambda index: body[index])
    rotated = body[start:] + body[:start]
    return tuple(rotated + [rotated[0]])


def validate_ids_and_fields(plan: Plan) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not plan.id:
        issues.append(
            _issue("missing_required_field", "error", "plan id is required", ["plan", "id"])
        )
    if not plan.output_goal:
        issues.append(
            _issue(
                "missing_required_field",
                "error",
                "plan output_goal is required",
                ["plan", "output_goal"],
            )
        )

    if plan.schema_version != PLAN_SCHEMA_VERSION:
        issues.append(
            _issue(
                "invalid_schema_version",
                "error",
                (
                    f"plan schema_version {plan.schema_version} is not supported; "
                    f"expected {PLAN_SCHEMA_VERSION}"
                ),
                ["plan", "schema_version"],
            )
        )

    seen_ids: dict[str, str] = {}
    for item_id, item in plan.items.items():
        if item.id != item_id:
            issues.append(
                _issue(
                    "duplicate_item_id",
                    "error",
                    f"item key {item_id!r} does not match embedded id {item.id!r}",
                    [item_id],
                )
            )
        if item.id in seen_ids:
            issues.append(
                _issue(
                    "duplicate_item_id",
                    "error",
                    f"duplicate stable item id: {item.id}",
                    [item.id],
                )
            )
        else:
            seen_ids[item.id] = item_id

        if not is_active_item(item):
            continue

        if not item.order_key:
            issues.append(
                _issue(
                    "missing_required_field",
                    "error",
                    "active item order_key is required",
                    [item.id, "order_key"],
                )
            )
        if not item.title:
            issues.append(
                _issue(
                    "missing_required_field",
                    "error",
                    "active item title is required",
                    [item.id, "title"],
                )
            )

    return issues


def validate_hierarchy(plan: Plan) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    reported_cycles: set[tuple[str, ...]] = set()

    for item_id, item in sorted(plan.items.items()):
        if not is_active_item(item):
            continue

        if item.parent_id == item_id:
            issues.append(
                _issue(
                    "self_parent",
                    "error",
                    f"item cannot be its own parent: {item_id}",
                    [item_id],
                )
            )
            continue

        if item.parent_id is not None:
            parent = plan.items.get(item.parent_id)
            if parent is None:
                issues.append(
                    _issue(
                        "missing_parent",
                        "error",
                        f"parent does not exist: {item.parent_id}",
                        [item_id, item.parent_id],
                    )
                )
            elif not is_active_item(parent):
                issues.append(
                    _issue(
                        "inactive_parent",
                        "error",
                        f"parent is not active: {item.parent_id}",
                        [item_id, item.parent_id],
                    )
                )

        cycle = find_hierarchy_cycle(plan, item_id)
        if cycle is not None:
            key = _normalized_cycle_key(cycle)
            if key not in reported_cycles:
                reported_cycles.add(key)
                issues.append(
                    _issue(
                        "hierarchy_cycle",
                        "error",
                        f"hierarchy cycle: {' -> '.join(cycle)}",
                        cycle,
                    )
                )

    walk = walk_active_tree(plan)
    for duplicate_id in walk.duplicate_ids:
        issues.append(
            _issue(
                "traversal_duplicate",
                "error",
                f"active item appears more than once in traversal: {duplicate_id}",
                [duplicate_id],
            )
        )

    traversal_ids = [item_id for item_id, _ in walk.rows]
    active_ids = {
        active_id
        for active_id, active_item in plan.items.items()
        if is_active_item(active_item)
    }
    traversal_set = set(traversal_ids)

    for missing_id in sorted(active_ids - traversal_set):
        issues.append(
            _issue(
                "traversal_missing_active_item",
                "error",
                f"active item missing from display traversal: {missing_id}",
                [missing_id],
            )
        )

    for extra_id in sorted(traversal_set - active_ids):
        issues.append(
            _issue(
                "traversal_extra_item",
                "error",
                f"traversal includes inactive or unknown item: {extra_id}",
                [extra_id],
            )
        )

    return issues


def validate_dependencies(
    plan: Plan,
    dispositions: DispositionMap | None = None,
    *,
    is_review_blocked: ReviewBlockedFn | None = None,
) -> list[ValidationIssue]:
    dispositions = dispositions or {}
    issues: list[ValidationIssue] = []

    cycle_issue = dependency_cycle_issue(plan)
    if cycle_issue is not None:
        issues.append(
            _issue(
                cycle_issue.code,
                "error",
                f"dependency cycle: {' -> '.join(cycle_issue.path)}",
                cycle_issue.path,
            )
        )

    for item_id, item in sorted(plan.items.items()):
        if not is_active_item(item):
            continue

        seen_deps: set[str] = set()
        for dep_id in item.depends_on:
            if dep_id in seen_deps:
                issues.append(
                    _issue(
                        "duplicate_dependency",
                        "error",
                        f"duplicate dependency edge: {item_id} -> {dep_id}",
                        [item_id, dep_id],
                    )
                )
            seen_deps.add(dep_id)

            if dep_id == item_id:
                issues.append(
                    _issue(
                        "self_dependency",
                        "error",
                        f"item depends on itself: {item_id}",
                        [item_id],
                    )
                )
                continue

            dep_item = plan.items.get(dep_id)
            if dep_item is None:
                issues.append(
                    _issue(
                        "missing_dependency_target",
                        "error",
                        f"dependency target does not exist: {dep_id}",
                        [item_id, dep_id],
                    )
                )
            elif not is_active_item(dep_item):
                issues.append(
                    _issue(
                        "inactive_dependency_target",
                        "error",
                        f"dependency target is not active: {dep_id}",
                        [item_id, dep_id],
                    )
                )

        disposition = dispositions.get(item_id)
        if disposition in SATISFIED_DISPOSITIONS:
            for dep_id in item.depends_on:
                if dep_id not in plan.items:
                    continue
                dep_result = resolve_satisfaction(plan, dep_id, dispositions)
                if dep_result.state == "satisfied":
                    continue
                blocker_reason = dep_result.blocker_reason or "unsatisfied_dependency"
                issues.append(
                    _issue(
                        "unsatisfied_dependency_for_completed_item",
                        "error",
                        (
                            f"satisfied item {item_id} depends on unsatisfied item {dep_id}: "
                            f"{blocker_reason}"
                        ),
                        [item_id, dep_id],
                    )
                )

    has_hierarchy_cycle = any(
        find_hierarchy_cycle(plan, item_id) is not None for item_id in plan.items
    )
    has_missing_parent = any(
        item.parent_id is not None and item.parent_id not in plan.items
        for item in plan.items.values()
        if is_active_item(item)
    )
    has_duplicate_ids = bool(walk_active_tree(plan).duplicate_ids)
    if (
        cycle_issue is None
        and not has_hierarchy_cycle
        and not has_missing_parent
        and not has_duplicate_ids
    ):
        deadlock = detect_deadlock(
            plan,
            dispositions,
            is_review_blocked=is_review_blocked,
        )
        if deadlock is not None and deadlock.cause != "cycle":
            issues.append(
                _issue(
                    "dependency_deadlock",
                    "error",
                    deadlock.explanation,
                    deadlock.waiting_item_ids,
                )
            )

    return issues


def validate_soft_limits(
    plan: Plan,
    limits: PlanningLimits,
    mode: ValidationMode,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for item_id, item in sorted(plan.items.items()):
        if not is_active_item(item):
            continue

        budget = compute_planning_budget(plan, item_id, limits)
        if budget.depth > limits.max_depth:
            issues.append(
                _issue(
                    "exceeded_depth_limit",
                    _severity_for_mode(mode, "warning"),
                    f"item depth {budget.depth} exceeds max_depth {limits.max_depth}",
                    [item_id],
                )
            )
        if budget.direct_children > limits.max_expansion_per_item:
            issues.append(
                _issue(
                    "exceeded_expansion_limit",
                    _severity_for_mode(mode, "warning"),
                    (
                        f"item has {budget.direct_children} children, exceeding "
                        f"max_expansion_per_item {limits.max_expansion_per_item}"
                    ),
                    [item_id],
                )
            )

    return issues


def _validate_digest_pair(
    label: str,
    actual: str | None,
    expected: str | None,
) -> ValidationIssue | None:
    if actual is None and expected is None:
        return None
    if actual is None or expected is None:
        return _issue(
            "digest_not_checked",
            "warning",
            f"{label} digest was not fully provided for comparison",
            [label],
        )
    if actual != expected:
        return _issue(
            "digest_mismatch",
            "error",
            f"{label} digest does not match the reviewed version",
            [label],
        )
    return None


def validate_review_hooks(
    plan: Plan,
    review_state: ReviewState,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for finding in review_state.unresolved_blocking_findings:
        issues.append(
            _issue(
                "unresolved_blocking_finding",
                "error",
                f"blocking whole-plan finding remains unresolved: {finding}",
                [finding],
            )
        )

    if review_state.approved_revision is not None:
        if review_state.approved_revision != plan.revision:
            issues.append(
                _issue(
                    "approval_revision_mismatch",
                    "error",
                    (
                        f"whole-plan approval targets revision {review_state.approved_revision}, "
                        f"but current plan revision is {plan.revision}"
                    ),
                    ["plan", "revision"],
                )
            )
    elif not review_state.unresolved_blocking_findings:
        issues.append(
            _issue(
                "review_state_not_checked",
                "warning",
                "approved revision was not provided for comparison",
                ["plan", "revision"],
            )
        )

    return issues


def validate_digest_hooks(
    plan: Plan,
    digests: DigestBundle,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if digests.plan_revision is not None and digests.plan_revision != plan.revision:
        issues.append(
            _issue(
                "approval_revision_mismatch",
                "error",
                (
                    f"digest bundle targets revision {digests.plan_revision}, "
                    f"but current plan revision is {plan.revision}"
                ),
                ["plan", "revision"],
            )
        )

    for label, actual, expected in (
        ("plan", digests.actual_plan_digest, digests.expected_plan_digest),
        ("input", digests.input_digest, digests.expected_input_digest),
        ("output_goal", digests.output_goal_digest, digests.expected_output_goal_digest),
        ("config", digests.config_digest, digests.expected_config_digest),
        ("context", digests.context_digest, digests.expected_context_digest),
    ):
        digest_issue = _validate_digest_pair(label, actual, expected)
        if digest_issue is not None:
            issues.append(digest_issue)

    return issues


def validate_plan(
    plan: Plan,
    *,
    limits: PlanningLimits | None = None,
    review_state: ReviewState | None = None,
    digests: DigestBundle | None = None,
    dispositions: DispositionMap | None = None,
    reviews: list[dict[str, Any]] | None = None,
    review_types: frozenset[str] | None = None,
    mode: ValidationMode = "draft",
) -> ValidationResult:
    effective_limits = limits or PlanningLimits()
    issues: list[ValidationIssue] = []
    is_review_blocked = build_is_review_blocked_fn(reviews, review_types=review_types)

    issues.extend(validate_ids_and_fields(plan))
    issues.extend(validate_hierarchy(plan))
    issues.extend(
        validate_dependencies(
            plan,
            dispositions,
            is_review_blocked=is_review_blocked,
        )
    )
    issues.extend(validate_soft_limits(plan, effective_limits, mode))

    if review_state is not None:
        issues.extend(validate_review_hooks(plan, review_state))
    if digests is not None:
        issues.extend(validate_digest_hooks(plan, digests))

    return ValidationResult(issues=issues)
