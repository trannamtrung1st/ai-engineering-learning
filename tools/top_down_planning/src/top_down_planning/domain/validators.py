"""Deterministic plan validation (proposal §6.2–§6.3, §9, §12.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from top_down_planning.domain.approval_digests import reject_legacy_approved_config_digest
from top_down_planning.domain.dependencies import dependency_cycle_issue
from top_down_planning.domain.dispositions import DispositionMap, SATISFIED_DISPOSITIONS
from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits, Scope
from top_down_planning.domain.plan_schema import (
    PLANNING_STATUSES,
    PLAN_SCHEMA_VERSION,
    UNSUPPORTED_PLAN_SCHEMA_MESSAGE,
)
from top_down_planning.domain.plan_tree import (
    DEFAULT_PLAN_ROOT_TITLE,
    PLAN_ROOT_ITEM_ID,
    active_children_of,
    compute_planning_budget,
    find_hierarchy_cycle,
    is_active_item,
    is_usable_item_id,
    is_usable_parent_reference,
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
    unresolved_required_findings: list[str] = field(default_factory=list)


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
    config_contract_digest: str | None = None
    expected_config_contract_digest: str | None = None
    context_spec_digest: str | None = None
    expected_context_spec_digest: str | None = None


def build_plan_approval_validation_context(
    *,
    plan: Plan,
    approval: dict[str, Any],
    actual_plan_digest: str,
    actual_config_contract_digest: str,
    actual_input_digest: str,
    actual_output_goal_digest: str,
    actual_context_spec_digest: str | None = None,
) -> tuple[ReviewState, DigestBundle]:
    """Build approval-mode review and digest bindings for the current plan revision."""

    from top_down_planning.domain.plan_schema import (
        require_non_negative_int,
        require_string,
    )
    from top_down_planning.domain.reviews import required_unresolved_finding_ids_from_payload

    approved_digests = approval.get("approved_digests")
    if approved_digests is not None and not isinstance(approved_digests, dict):
        raise ValueError("approved_digests must be an object")
    expected_digests: dict[str, str] = {}
    if isinstance(approved_digests, dict):
        for key, value in approved_digests.items():
            expected_digests[require_string(key, "approved_digests key")] = require_string(
                value,
                "approved_digests value",
            )
    reject_legacy_approved_config_digest(expected_digests or None)
    review_state = ReviewState(
        approved_revision=require_non_negative_int(
            approval["target_revision"],
            "target_revision",
        ),
        unresolved_required_findings=required_unresolved_finding_ids_from_payload(
            approval
        ),
    )
    digest_bundle = DigestBundle(
        plan_revision=plan.revision,
        expected_plan_digest=expected_digests.get("plan"),
        actual_plan_digest=actual_plan_digest,
        input_digest=actual_input_digest,
        expected_input_digest=expected_digests.get("input"),
        output_goal_digest=actual_output_goal_digest,
        expected_output_goal_digest=expected_digests.get("output_goal"),
        config_contract_digest=actual_config_contract_digest,
        expected_config_contract_digest=expected_digests.get("config_contract"),
        context_spec_digest=actual_context_spec_digest,
        expected_context_spec_digest=expected_digests.get("context_spec"),
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


def _validate_string_list_issues(
    value: Any,
    *,
    path: list[str],
    field_name: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(value, list):
        issues.append(
            _issue(
                "invalid_plan_field",
                "error",
                f"{field_name} must be a list",
                path,
            )
        )
        return issues
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    f"{field_name} entries must be non-empty strings",
                    [*path, str(index)],
                )
            )
    return issues


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


def severity_for_validation_mode(
    mode: ValidationMode,
    draft_severity: ValidationSeverity,
) -> ValidationSeverity:
    """Escalate draft warnings to errors in approval mode."""

    return _severity_for_mode(mode, draft_severity)


def _normalized_cycle_key(cycle: list[str]) -> tuple[str, ...]:
    if len(cycle) < 2:
        return tuple(cycle)
    body = cycle[:-1] if cycle[-1] == cycle[0] else list(cycle)
    if not body:
        return tuple(cycle)
    start = min(range(len(body)), key=lambda index: body[index])
    rotated = body[start:] + body[:start]
    return tuple(rotated + [rotated[0]])


def _has_active_work_descendant(plan: Plan, item_id: str) -> bool:
    from top_down_planning.domain.plan_tree import active_children_of

    stack = list(active_children_of(plan, item_id))
    while stack:
        child = stack.pop()
        if child.kind == "work":
            return True
        stack.extend(active_children_of(plan, child.id))
    return False


def _contract_fingerprint(item: PlanItem) -> tuple[Any, ...]:
    if not isinstance(item.scope, Scope):
        return ("", "", (), (), ())
    return (
        _safe_strip(item.title).casefold(),
        _safe_strip(item.outcome).casefold(),
        _safe_string_list_fingerprint(item.scope.includes),
        _safe_string_list_fingerprint(item.scope.excludes),
        _safe_string_list_fingerprint(item.acceptance),
    )


def _safe_string_list_fingerprint(entries: Any) -> tuple[str, ...]:
    if not isinstance(entries, list):
        return ()
    return tuple(
        _safe_strip(entry).casefold() for entry in entries if isinstance(entry, str)
    )


def _item_path_prefix(item_id: str, item: PlanItem) -> str:
    if isinstance(item.id, str) and item.id.strip():
        return item.id
    return item_id


def _validate_scope_field_issues(
    scope: Any,
    *,
    path: list[str],
) -> list[ValidationIssue]:
    if isinstance(scope, Scope):
        return []
    return [
        _issue(
            "invalid_plan_field",
            "error",
            "scope must be a Scope object",
            path,
        )
    ]


def _safe_strip(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


@dataclass(frozen=True)
class PlanItemsStructure:
    issues: list[ValidationIssue]
    entries: dict[str, PlanItem]
    semantic_safe_keys: frozenset[str]


def _item_nested_field_issues(item_id: str, item: PlanItem) -> list[ValidationIssue]:
    path_prefix = _item_path_prefix(item_id, item)
    issues: list[ValidationIssue] = []
    scope_issues = _validate_scope_field_issues(
        item.scope,
        path=[path_prefix, "scope"],
    )
    issues.extend(scope_issues)
    if isinstance(item.scope, Scope):
        issues.extend(
            _validate_string_list_issues(
                item.scope.includes,
                path=[path_prefix, "scope", "includes"],
                field_name="scope.includes",
            )
        )
        issues.extend(
            _validate_string_list_issues(
                item.scope.excludes,
                path=[path_prefix, "scope", "excludes"],
                field_name="scope.excludes",
            )
        )
    for field_name in ("boundaries", "acceptance", "depends_on", "risks", "source_refs"):
        issues.extend(
            _validate_string_list_issues(
                getattr(item, field_name),
                path=[path_prefix, field_name],
                field_name=field_name,
            )
        )
    return issues


def _semantic_safe_entries(structure: PlanItemsStructure) -> dict[str, PlanItem]:
    return {
        item_id: item
        for item_id, item in structure.entries.items()
        if item_id in structure.semantic_safe_keys
    }


def _plan_items_key_label(key: Any) -> str:
    if isinstance(key, str):
        return key
    return str(key)


def _analyze_plan_items(plan: Plan) -> PlanItemsStructure:
    issues: list[ValidationIssue] = []
    entries: dict[str, PlanItem] = {}

    raw_items = plan.items
    if not isinstance(raw_items, dict):
        issues.append(
            _issue(
                "invalid_plan_field",
                "error",
                "plan items must be a mapping",
                ["plan", "items"],
            )
        )
        return PlanItemsStructure(
            issues=issues,
            entries=entries,
            semantic_safe_keys=frozenset(),
        )

    semantic_safe_keys: set[str] = set()
    for key, value in raw_items.items():
        if not isinstance(key, str):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "plan item key must be a string",
                    ["plan", "items", _plan_items_key_label(key)],
                )
            )
            continue
        if not isinstance(value, PlanItem):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "plan item value must be a PlanItem",
                    ["plan", "items", key],
                )
            )
            continue
        entries[key] = value
        nested_issues = _item_nested_field_issues(key, value)
        issues.extend(nested_issues)
        if (
            not nested_issues
            and is_usable_parent_reference(value.parent_id)
            and is_usable_item_id(value.id)
            and isinstance(value.order_key, str)
        ):
            semantic_safe_keys.add(key)

    return PlanItemsStructure(
        issues=issues,
        entries=entries,
        semantic_safe_keys=frozenset(semantic_safe_keys),
    )


def _sorted_plan_item_entries(entries: dict[str, PlanItem]) -> list[tuple[str, PlanItem]]:
    return sorted(entries.items())


def validate_canonical_root(plan: Plan) -> list[ValidationIssue]:
    """Require exactly one active canonical aggregate root and a single-root tree."""

    structure = _analyze_plan_items(plan)
    issues: list[ValidationIssue] = list(structure.issues)
    entries = structure.entries

    root = entries.get(PLAN_ROOT_ITEM_ID)
    if root is None:
        issues.append(
            _issue(
                "missing_canonical_root",
                "error",
                f"plan requires canonical root item {PLAN_ROOT_ITEM_ID!r}",
                [PLAN_ROOT_ITEM_ID],
            )
        )
        return issues

    if not is_active_item(root):
        issues.append(
            _issue(
                "inactive_canonical_root",
                "error",
                f"canonical root {PLAN_ROOT_ITEM_ID!r} must be active",
                [PLAN_ROOT_ITEM_ID, "planning_status"],
            )
        )

    if root.parent_id is not None:
        issues.append(
            _issue(
                "invalid_canonical_root_parent",
                "error",
                f"canonical root {PLAN_ROOT_ITEM_ID!r} must have parent_id null",
                [PLAN_ROOT_ITEM_ID, "parent_id"],
            )
        )

    if root.kind != "aggregate":
        issues.append(
            _issue(
                "invalid_canonical_root_kind",
                "error",
                f"canonical root {PLAN_ROOT_ITEM_ID!r} must have kind aggregate",
                [PLAN_ROOT_ITEM_ID, "kind"],
            )
        )

    active_roots = [
        item.id
        for item in entries.values()
        if is_active_item(item)
        and item.parent_id is None
        and isinstance(item.id, str)
    ]
    if len(active_roots) > 1:
        issues.append(
            _issue(
                "multiple_active_roots",
                "error",
                "exactly one active root is allowed; found "
                + ", ".join(sorted(active_roots)),
                sorted(active_roots),
            )
        )

    for item_id, item in _sorted_plan_item_entries(entries):
        if not is_active_item(item):
            continue
        if item_id == PLAN_ROOT_ITEM_ID:
            continue
        if item.parent_id is None:
            issues.append(
                _issue(
                    "multiple_active_roots",
                    "error",
                    f"active item {item_id!r} must not be a root",
                    [item_id, "parent_id"],
                )
            )

    return issues


def validate_root_item_populated(plan: Plan) -> list[ValidationIssue]:
    """Require a named root outcome once decomposition children exist."""

    issues: list[ValidationIssue] = []
    root = _analyze_plan_items(plan).entries.get(PLAN_ROOT_ITEM_ID)
    if root is None or not is_active_item(root):
        return issues
    if not active_children_of(plan, PLAN_ROOT_ITEM_ID):
        return issues

    if _safe_strip(root.title).casefold() == DEFAULT_PLAN_ROOT_TITLE.casefold():
        issues.append(
            _issue(
                "default_root_title",
                "error",
                (
                    f"root item {PLAN_ROOT_ITEM_ID} still has the seeded title "
                    f"{DEFAULT_PLAN_ROOT_TITLE!r}; update it with update_item before "
                    "signaling candidate_plan_ready"
                ),
                [PLAN_ROOT_ITEM_ID, "title"],
            )
        )
    if not _safe_strip(root.outcome):
        issues.append(
            _issue(
                "missing_root_outcome",
                "error",
                (
                    f"root item {PLAN_ROOT_ITEM_ID} requires a non-empty outcome "
                    "once it has active child items"
                ),
                [PLAN_ROOT_ITEM_ID, "outcome"],
            )
        )
    return issues


def _work_item_has_scope_contract(item: PlanItem) -> bool:
    from top_down_planning.domain.item_contract import has_item_scope_contract

    return has_item_scope_contract(item)


def validate_work_item_scope_contract(
    plan: Plan,
    *,
    mode: ValidationMode = "draft",
) -> list[ValidationIssue]:
    """Require item-level scope or boundaries on active work leaves."""

    issues: list[ValidationIssue] = []
    structure = _analyze_plan_items(plan)
    safe_entries = _semantic_safe_entries(structure)
    for item_id, item in _sorted_plan_item_entries(safe_entries):
        if not is_active_item(item) or item.kind != "work":
            continue
        if _work_item_has_scope_contract(item):
            continue
        issues.append(
            _issue(
                "missing_work_item_scope_contract",
                _severity_for_mode(mode, "warning"),
                (
                    f"work item {item_id} requires item-level scope.includes, "
                    "scope.excludes, or boundaries"
                ),
                [item_id, "scope"],
            )
        )
    return issues


def validate_plan_quality_warnings(plan: Plan) -> list[ValidationIssue]:
    """Advisory semantic warnings that never escalate to hard errors alone."""

    issues: list[ValidationIssue] = []
    structure = _analyze_plan_items(plan)
    entries = structure.entries
    safe_keys = structure.semantic_safe_keys

    for item_id, item in _sorted_plan_item_entries(entries):
        if item_id not in safe_keys or not is_active_item(item):
            continue
        if item.kind == "aggregate":
            from top_down_planning.domain.plan_tree import active_children_of

            if not active_children_of(plan, item_id):
                issues.append(
                    _issue(
                        "aggregate_without_descendants",
                        "warning",
                        f"aggregate item {item_id} has no active descendants",
                        [item_id, "kind"],
                    )
                )
            continue
        if item.kind != "work":
            continue
        if _has_active_work_descendant(plan, item_id):
            issues.append(
                _issue(
                    "executable_parent_overlap",
                    "warning",
                    (
                        f"work item {item_id} has executable descendants; "
                        "verify that parent and child work do not overlap"
                    ),
                    [item_id],
                )
            )

    siblings_by_parent: dict[str | None, list[tuple[str, PlanItem]]] = {}
    for item_id, item in entries.items():
        if item_id not in safe_keys or not is_active_item(item):
            continue
        if not is_usable_parent_reference(item.parent_id):
            continue
        siblings_by_parent.setdefault(item.parent_id, []).append((item_id, item))

    for siblings in siblings_by_parent.values():
        # Direct siblings only; keep duplicate detection conservative (exact match).
        by_fingerprint: dict[tuple[Any, ...], list[str]] = {}
        for item_id, sibling in siblings:
            fingerprint = _contract_fingerprint(sibling)
            # Skip empty/near-empty contracts to avoid noisy false positives.
            if fingerprint == ("", "", (), (), ()):
                continue
            by_fingerprint.setdefault(fingerprint, []).append(item_id)
        for item_ids in by_fingerprint.values():
            if len(item_ids) < 2:
                continue
            joined = ", ".join(sorted(item_ids))
            issues.append(
                _issue(
                    "duplicate_looking_sibling_contracts",
                    "warning",
                    (
                        "sibling items have identical title/outcome/scope/acceptance: "
                        f"{joined}"
                    ),
                    sorted(item_ids),
                )
            )

    return issues


def plan_advisory_warning_messages(plan: Plan) -> list[str]:
    """Semantic quality warnings for review packages and planning completion.

    Planning-budget soft limits (for example near/at depth) are surfaced only
    through plan check/snapshot draft validation, not through this helper.
    """

    return [issue.message for issue in validate_plan_quality_warnings(plan)]


def validate_ids_and_fields(plan: Plan) -> list[ValidationIssue]:
    structure = _analyze_plan_items(plan)
    issues: list[ValidationIssue] = list(structure.issues)

    if isinstance(plan.revision, bool) or not isinstance(plan.revision, int):
        issues.append(
            _issue(
                "invalid_plan_field",
                "error",
                "plan revision must be an integer",
                ["plan", "revision"],
            )
        )
    elif plan.revision < 0:
        issues.append(
            _issue(
                "invalid_plan_field",
                "error",
                "plan revision must be non-negative",
                ["plan", "revision"],
            )
        )

    if not isinstance(plan.id, str) or not plan.id.strip():
        issues.append(
            _issue("missing_required_field", "error", "plan id is required", ["plan", "id"])
        )
    if not isinstance(plan.output_goal, str) or not plan.output_goal.strip():
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
                UNSUPPORTED_PLAN_SCHEMA_MESSAGE,
                ["plan", "schema_version"],
            )
        )

    seen_ids: dict[str, str] = {}
    for item_id, item in _sorted_plan_item_entries(structure.entries):
        path_prefix = _item_path_prefix(item_id, item)

        if not isinstance(item.id, str) or not item.id.strip():
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "item id must be a non-empty string",
                    [item_id, "id"],
                )
            )
        elif item.id != item_id:
            issues.append(
                _issue(
                    "duplicate_item_id",
                    "error",
                    f"item key {item_id!r} does not match embedded id {item.id!r}",
                    [item_id],
                )
            )
        elif item.id in seen_ids:
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

        if not isinstance(item.planning_status, str):
            issues.append(
                _issue(
                    "invalid_planning_status",
                    "error",
                    (
                        "planning_status must be one of: "
                        + ", ".join(sorted(PLANNING_STATUSES))
                    ),
                    [path_prefix, "planning_status"],
                )
            )
        elif item.planning_status not in PLANNING_STATUSES:
            issues.append(
                _issue(
                    "invalid_planning_status",
                    "error",
                    (
                        "planning_status must be one of: "
                        + ", ".join(sorted(PLANNING_STATUSES))
                    ),
                    [path_prefix, "planning_status"],
                )
            )

        if item.planning_status == "superseded" and (
            not isinstance(item.superseded_by, str) or not item.superseded_by.strip()
        ):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "superseded items require superseded_by",
                    [path_prefix, "superseded_by"],
                )
            )
        if (
            isinstance(item.planning_status, str)
            and item.planning_status != "superseded"
            and item.superseded_by is not None
        ):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "superseded_by is only valid when planning_status is superseded",
                    [path_prefix, "superseded_by"],
                )
            )

        if not isinstance(item.outcome, str):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "item outcome must be a string",
                    [path_prefix, "outcome"],
                )
            )

        if item.parent_id is not None and not isinstance(item.parent_id, str):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "item parent_id must be a string or null",
                    [path_prefix, "parent_id"],
                )
            )

        if not is_active_item(item):
            continue

        if not isinstance(item.order_key, str) or not item.order_key.strip():
            issues.append(
                _issue(
                    "missing_required_field",
                    "error",
                    "active item order_key is required",
                    [path_prefix, "order_key"],
                )
            )
        if not isinstance(item.title, str) or not item.title.strip():
            issues.append(
                _issue(
                    "missing_required_field",
                    "error",
                    "active item title is required",
                    [path_prefix, "title"],
                )
            )
        if item.kind not in ("aggregate", "work"):
            issues.append(
                _issue(
                    "invalid_item_kind",
                    "error",
                    f"active item kind must be aggregate or work, got {item.kind!r}",
                    [path_prefix, "kind"],
                )
            )

    plan_scope_issues = _validate_scope_field_issues(
        plan.scope,
        path=["plan", "scope"],
    )
    issues.extend(plan_scope_issues)

    for field_name in ("boundaries", "constraints", "assumptions", "acceptance", "risks"):
        value = getattr(plan, field_name)
        if not isinstance(value, list):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    f"plan {field_name} must be a list",
                    ["plan", field_name],
                )
            )
            continue
        issues.extend(
            _validate_string_list_issues(
                value,
                path=["plan", field_name],
                field_name=f"plan {field_name}",
            )
        )

    issues.extend(
        _validate_string_list_issues(
            plan.input_refs,
            path=["plan", "input_refs"],
            field_name="plan input_refs",
        )
    )
    if not plan_scope_issues:
        issues.extend(
            _validate_string_list_issues(
                plan.scope.includes,
                path=["plan", "scope", "includes"],
                field_name="plan scope.includes",
            )
        )
        issues.extend(
            _validate_string_list_issues(
                plan.scope.excludes,
                path=["plan", "scope", "excludes"],
                field_name="plan scope.excludes",
            )
        )

    return issues


def validate_hierarchy(plan: Plan) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    reported_cycles: set[tuple[str, ...]] = set()

    structure = _analyze_plan_items(plan)
    issues.extend(structure.issues)
    item_entries = structure.entries
    safe_keys = structure.semantic_safe_keys
    siblings_by_parent: dict[str | None, list[tuple[str, PlanItem]]] = {}
    for item_id, item in item_entries.items():
        if not is_active_item(item):
            continue
        if not is_usable_parent_reference(item.parent_id):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "item parent_id must be a string or null",
                    [item_id, "parent_id"],
                )
            )
            continue
        siblings_by_parent.setdefault(item.parent_id, []).append((item_id, item))

    for parent_id, siblings in siblings_by_parent.items():
        seen_order_keys: dict[str, list[str]] = {}
        for item_id, sibling in siblings:
            if item_id not in safe_keys:
                continue
            if not isinstance(sibling.order_key, str) or not sibling.order_key.strip():
                continue
            seen_order_keys.setdefault(sibling.order_key, []).append(item_id)
        for order_key, item_ids in sorted(seen_order_keys.items()):
            if len(item_ids) < 2:
                continue
            path = [parent_id or PLAN_ROOT_ITEM_ID, "order_key", order_key]
            issues.append(
                _issue(
                    "duplicate_sibling_order_key",
                    "error",
                    (
                        "active siblings share order_key "
                        f"{order_key!r}: {', '.join(sorted(item_ids))}"
                    ),
                    path + sorted(item_ids),
                )
            )

    for item_id, item in _sorted_plan_item_entries(item_entries):
        if item_id not in safe_keys or not is_active_item(item):
            continue

        if not is_usable_parent_reference(item.parent_id):
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
            parent = item_entries.get(item.parent_id)
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

    traversal_ids = [item_id for item_id, _, _ in walk.rows]
    active_ids = {
        active_id
        for active_id, active_item in item_entries.items()
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
    structure = _analyze_plan_items(plan)
    issues: list[ValidationIssue] = list(structure.issues)
    item_entries = structure.entries
    safe_keys = structure.semantic_safe_keys

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

    for item_id, item in _sorted_plan_item_entries(item_entries):
        if item_id not in safe_keys or not is_active_item(item):
            continue

        if not isinstance(item.depends_on, list):
            issues.append(
                _issue(
                    "invalid_plan_field",
                    "error",
                    "depends_on must be a list",
                    [item_id, "depends_on"],
                )
            )
            continue

        seen_deps: set[str] = set()
        for dep_index, dep_id in enumerate(item.depends_on):
            if not isinstance(dep_id, str):
                issues.append(
                    _issue(
                        "invalid_plan_field",
                        "error",
                        "depends_on entries must be strings",
                        [item_id, "depends_on", str(dep_index)],
                    )
                )
                continue
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

            dep_item = item_entries.get(dep_id)
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
                if not isinstance(dep_id, str) or dep_id not in item_entries:
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
        find_hierarchy_cycle(plan, item_id) is not None for item_id in item_entries
    )
    has_missing_parent = any(
        isinstance(item.parent_id, str) and item.parent_id not in item_entries
        for item in item_entries.values()
        if is_active_item(item)
    )
    has_duplicate_ids = bool(walk_active_tree(plan).duplicate_ids)
    if (
        not structure.issues
        and cycle_issue is None
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
    structure = _analyze_plan_items(plan)

    for item_id in sorted(structure.semantic_safe_keys):
        item = structure.entries[item_id]
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
    *,
    mode: ValidationMode = "draft",
) -> ValidationIssue | None:
    if actual is None and expected is None:
        return None
    if actual is None or expected is None:
        return _issue(
            "digest_not_checked",
            _severity_for_mode(mode, "warning"),
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
    *,
    mode: ValidationMode = "draft",
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for finding in review_state.unresolved_required_findings:
        issues.append(
            _issue(
                "unresolved_required_finding",
                "error",
                f"required whole-plan finding remains unresolved: {finding}",
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
    elif not review_state.unresolved_required_findings:
        issues.append(
            _issue(
                "review_state_not_checked",
                _severity_for_mode(mode, "warning"),
                "approved revision was not provided for comparison",
                ["plan", "revision"],
            )
        )

    return issues


def validate_digest_hooks(
    plan: Plan,
    digests: DigestBundle,
    *,
    mode: ValidationMode = "draft",
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
        ("config_contract", digests.config_contract_digest, digests.expected_config_contract_digest),
        ("context_spec", digests.context_spec_digest, digests.expected_context_spec_digest),
    ):
        digest_issue = _validate_digest_pair(label, actual, expected, mode=mode)
        if digest_issue is not None:
            issues.append(digest_issue)

    return issues


def collect_plan_analysis_validation_issues(plan: Plan) -> list[ValidationIssue]:
    """Structured advisory issues for reviewer analysis_context."""

    seen: set[tuple[str, tuple[str, ...]]] = set()
    ordered: list[ValidationIssue] = []

    def add_issues(issues: list[ValidationIssue]) -> None:
        for issue in issues:
            key = (issue.code, tuple(issue.path))
            if key in seen:
                continue
            seen.add(key)
            ordered.append(issue)

    add_issues(validate_ids_and_fields(plan))
    add_issues(validate_canonical_root(plan))
    add_issues(validate_root_item_populated(plan))
    add_issues(validate_plan_quality_warnings(plan))
    add_issues(validate_work_item_scope_contract(plan, mode="draft"))
    add_issues(validate_hierarchy(plan))
    add_issues(validate_dependencies(plan))
    return ordered


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
    issues.extend(validate_canonical_root(plan))
    issues.extend(validate_root_item_populated(plan))
    issues.extend(validate_plan_quality_warnings(plan))
    issues.extend(validate_work_item_scope_contract(plan, mode=mode))
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
        issues.extend(validate_review_hooks(plan, review_state, mode=mode))
    if digests is not None:
        issues.extend(validate_digest_hooks(plan, digests, mode=mode))

    return ValidationResult(issues=issues)


def hard_validation_issue_keys(validation: ValidationResult) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (issue.code, tuple(issue.path))
        for issue in validation.issues
        if issue.severity == "error"
    }


def new_hard_validation_issues(
    before: ValidationResult,
    after: ValidationResult,
) -> list[ValidationIssue]:
    before_keys = hard_validation_issue_keys(before)
    return [
        issue
        for issue in after.issues
        if issue.severity == "error" and (issue.code, tuple(issue.path)) not in before_keys
    ]
