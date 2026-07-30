"""Application orchestrator for lifecycle transitions (proposal §17.2).

Owns plan → review → validate → produce → amend → review output → outcome.
"""

from top_down_planning.orchestrator.errors import OrchestratorError, ProviderRunError
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PLANNING,
    PLANNING_CONSTRUCTION_PHASES,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.focused_review import (
    FocusedReviewOrchestrator,
    FocusedReviewResult,
    build_focused_review_package,
)
from top_down_planning.orchestrator.plan_amendment import (
    PlanAmendmentOrchestrator,
    PlanAmendmentResult,
)
from top_down_planning.orchestrator.planning import (
    PlanningPhaseOrchestrator,
    PlanningPhaseResult,
    build_planner_context_manifest,
)
from top_down_planning.orchestrator.production import (
    ProductionPhaseOrchestrator,
    ProductionPhaseResult,
    build_producer_context_manifest,
)
from top_down_planning.orchestrator.whole_output_review import (
    WholeOutputReviewOrchestrator,
    WholeOutputReviewResult,
    build_whole_output_review_package,
)
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.failure import mark_run_failed, sanitize_operational_error
from top_down_planning.orchestrator.resume import ResumeError, ResumePreconditions, validate_resume_preconditions
from top_down_planning.orchestrator.whole_plan_review import (
    WholePlanReviewOrchestrator,
    WholePlanReviewResult,
    build_whole_plan_review_package,
)

__all__ = [
    "OUTPUT_VALIDATED",
    "FocusedReviewOrchestrator",
    "FocusedReviewResult",
    "OrchestratorError",
    "PLANNING",
    "PLANNING_CONSTRUCTION_PHASES",
    "PLAN_AMENDMENT",
    "PLAN_VALIDATED",
    "PRODUCTION",
    "PlanAmendmentOrchestrator",
    "PlanAmendmentResult",
    "PlanningPhaseOrchestrator",
    "PlanningPhaseResult",
    "ProductionPhaseOrchestrator",
    "ProductionPhaseResult",
    "ProviderRunError",
    "ResumeError",
    "ResumePreconditions",
    "RunEngine",
    "WHOLE_OUTPUT_REVIEW",
    "WHOLE_PLAN_REVIEW",
    "WholeOutputReviewOrchestrator",
    "WholeOutputReviewResult",
    "WholePlanReviewOrchestrator",
    "WholePlanReviewResult",
    "build_focused_review_package",
    "build_planner_context_manifest",
    "build_producer_context_manifest",
    "build_whole_output_review_package",
    "build_whole_plan_review_package",
    "mark_run_failed",
    "sanitize_operational_error",
    "validate_resume_preconditions",
]
