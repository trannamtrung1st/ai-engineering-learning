"""Core domain models and rules (proposal §17.1).

Pure plan, dependency, review, production, and outcome logic. This layer must
not import CLI, provider, persistence, or orchestrator code.
"""

from top_down_planning.domain.dependencies import (
    DependencyCycleIssue,
    active_dependencies,
    active_dependency_edges,
    dependency_cycle_issue,
    find_dependency_cycle,
)
from top_down_planning.domain.dispositions import (
    SATISFIED_DISPOSITIONS,
    TERMINAL_DISPOSITIONS,
    DispositionMap,
    TerminalDisposition,
    is_satisfied_disposition,
    is_terminal_disposition,
)
from top_down_planning.domain.errors import (
    DependencyCycleError,
    DomainError,
    InvalidMutationError,
    RevisionConflictError,
    UnknownItemError,
)
from top_down_planning.domain.models import (
    ApplyResult,
    Plan,
    PlanItem,
    PlanningBudget,
    PlanningLimits,
    Scope,
)
from top_down_planning.domain.mutations import apply_operations
from top_down_planning.domain.plan_tree import (
    display_traversal,
    find_hierarchy_cycle,
    walk_active_tree,
)
from top_down_planning.domain.readiness import (
    DeadlockReport,
    ReadyView,
    SatisfactionResult,
    compute_ready_view,
    detect_deadlock,
    is_applicable_item,
    is_dependency_satisfied,
    is_terminal_item,
    resolve_satisfaction,
)
from top_down_planning.domain.validators import (
    DigestBundle,
    ReviewState,
    ValidationIssue,
    ValidationResult,
    validate_plan,
)

__all__ = [
    "ApplyResult",
    "DeadlockReport",
    "DigestBundle",
    "DependencyCycleError",
    "DependencyCycleIssue",
    "DispositionMap",
    "DomainError",
    "InvalidMutationError",
    "Plan",
    "PlanItem",
    "PlanningBudget",
    "PlanningLimits",
    "ReadyView",
    "ReviewState",
    "RevisionConflictError",
    "SATISFIED_DISPOSITIONS",
    "SatisfactionResult",
    "Scope",
    "TERMINAL_DISPOSITIONS",
    "TerminalDisposition",
    "UnknownItemError",
    "ValidationIssue",
    "ValidationResult",
    "active_dependencies",
    "active_dependency_edges",
    "apply_operations",
    "compute_ready_view",
    "dependency_cycle_issue",
    "detect_deadlock",
    "display_traversal",
    "find_dependency_cycle",
    "find_hierarchy_cycle",
    "is_applicable_item",
    "is_dependency_satisfied",
    "is_satisfied_disposition",
    "is_terminal_disposition",
    "is_terminal_item",
    "resolve_satisfaction",
    "validate_plan",
    "walk_active_tree",
]
