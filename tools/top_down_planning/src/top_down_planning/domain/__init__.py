"""Core domain models and rules (proposal §17.1).

Pure plan, dependency, review, production, and outcome logic. This layer must
not import CLI, provider, persistence, or orchestrator code.
"""

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
from top_down_planning.domain.plan_tree import display_traversal

__all__ = [
    "ApplyResult",
    "DependencyCycleError",
    "DomainError",
    "InvalidMutationError",
    "Plan",
    "PlanItem",
    "PlanningBudget",
    "PlanningLimits",
    "RevisionConflictError",
    "Scope",
    "UnknownItemError",
    "apply_operations",
    "display_traversal",
]
