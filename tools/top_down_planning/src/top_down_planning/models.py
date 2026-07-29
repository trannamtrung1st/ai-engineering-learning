"""Typed planning state, agent contracts, and runtime models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = 2
DEFAULT_CURSOR_MODEL = "composer-2.5"
DEFAULT_INLINE_EMBED_THRESHOLD = 4000


class DecompositionStatus(str, Enum):
    NEEDS_EXPANSION = "needs_expansion"
    EXPANDED = "expanded"
    ACTIONABLE = "actionable"
    BLOCKED = "blocked"
    OUT_OF_SCOPE = "out_of_scope"


class ReadinessStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    BLOCKED = "blocked"


class FinalStatus(str, Enum):
    PLANNING = "planning"
    COMPLETE = "complete"
    INCOMPLETE_BLOCKED = "incomplete_blocked"
    INCOMPLETE_LIMIT_REACHED = "incomplete_limit_reached"
    FAILED = "failed"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    CONFIRMED = "confirmed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class BlockedConstraintCode(str, Enum):
    MAX_CHILDREN_EXCEEDED = "max_children_exceeded"


class RunActiveStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanningLimits(BaseModel):
    max_iterations: int = 50
    max_depth: int = 6
    max_items: int = 200
    max_children_per_expansion: int = 12
    max_retries: int = 3
    session_timeout_seconds: int = 600
    parse_error_threshold: int = 20


class BatchStrategy(str, Enum):
    SINGLE = "single"
    COHERENT = "coherent"
    THROUGHPUT = "throughput"


class WholePlanContextMode(str, Enum):
    EMBEDDED = "embedded"
    REFERENCED = "referenced"
    HYBRID = "hybrid"


class RenderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = 3
    batch_strategy: BatchStrategy = BatchStrategy.COHERENT
    max_retries: int = 3
    whole_plan_context: WholePlanContextMode = WholePlanContextMode.HYBRID
    max_context_characters: int = 30000
    final_review: bool = True
    max_batch_revision_cycles: int = 1
    max_final_revision_cycles: int = 2
    scaffold: bool = True
    artifact_ignore_patterns: list[str] = Field(default_factory=list)


class RenderStage(str, Enum):
    SCAFFOLD = "scaffold"
    BATCHES = "batches"
    FINAL_REVIEW = "final_review"
    COMPLETE = "complete"


class RenderBatchStatus(str, Enum):
    PENDING = "pending"
    AUTHORING = "authoring"
    REVIEWING = "reviewing"
    REVISING = "revising"
    APPROVED = "approved"
    FAILED = "failed"
    BLOCKED = "blocked"


class RenderOutputReviewStatus(str, Enum):
    PENDING = "pending"
    SKIPPED = "skipped"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class DeliverableStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class RenderBatchItem(BaseModel):
    batch_index: int
    item_ids: list[str]
    dependencies: list[str] = Field(default_factory=list)
    status: RenderBatchStatus = RenderBatchStatus.PENDING
    revision_cycle: int = 0
    title: str = ""


class RenderBatchSchedule(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    plan_digest: str
    output_goal_digest: str
    render_config_digest: str
    batches: list[RenderBatchItem] = Field(default_factory=list)


class RenderState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    stage: RenderStage = RenderStage.SCAFFOLD
    run_id: str = ""
    plan_digest: str = ""
    output_goal_digest: str = ""
    render_config_digest: str = ""
    schedule_digest: str = ""
    current_batch_index: int = 0
    artifact_paths: list[str] = Field(default_factory=list)
    deliverable_output_digest: str | None = None
    output_review_status: RenderOutputReviewStatus = RenderOutputReviewStatus.PENDING
    deliverable_status: DeliverableStatus = DeliverableStatus.PENDING
    final_revision_cycle: int = 0
    scaffold_complete: bool = False
    updated_at: datetime | None = None


class GenerationConfig(BaseModel):
    batch_strategy: BatchStrategy = BatchStrategy.COHERENT
    batch_size: int = 3
    concurrent_batches: int = 3
    max_context_characters: int = 30000
    whole_plan_context: WholePlanContextMode = WholePlanContextMode.HYBRID


class ReviewConfig(BaseModel):
    enabled: bool = True
    max_revision_cycles: int = 1
    max_retries: int = 3


class SourceMetadata(BaseModel):
    input_file: str
    output_goal: str
    output_goal_file: str | None = None
    input_digest: str
    output_goal_digest: str
    stop_hint: str | None = None
    stop_hint_file: str | None = None
    stop_hint_digest: str | None = None


class PlanItem(BaseModel):
    id: str
    parent_id: str | None = None
    title: str
    objective: str
    depth: int = 0
    order: int = 1
    decomposition_status: DecompositionStatus = DecompositionStatus.NEEDS_EXPANSION
    readiness_status: ReadinessStatus = ReadinessStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    blocked_constraint_code: BlockedConstraintCode | None = None
    blocked_required_min_children: int | None = None
    out_of_scope_reason: str | None = None


class ResultMetadata(BaseModel):
    status: FinalStatus = FinalStatus.PLANNING
    review_status: ReviewStatus = ReviewStatus.PENDING
    summary: str | None = None


class PlanState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    source: SourceMetadata
    plan: list[PlanItem] = Field(default_factory=list)
    result: ResultMetadata = Field(default_factory=ResultMetadata)

    def item_by_id(self, item_id: str) -> PlanItem | None:
        for item in self.plan:
            if item.id == item_id:
                return item
        return None

    def children_of(self, parent_id: str | None) -> list[PlanItem]:
        return sorted(
            [item for item in self.plan if item.parent_id == parent_id],
            key=lambda item: item.order,
        )


def _validated_optional_detail(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty")
    return stripped


class ChildDraft(BaseModel):
    ref: str | None = None
    title: str
    objective: str
    dependencies: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("title", "objective")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class ExpandOperation(BaseModel):
    type: Literal["expand"] = "expand"
    node_id: str
    reason: str = ""
    title: str | None = None
    objective: str | None = None
    children: list[ChildDraft]

    @field_validator("title", "objective")
    @classmethod
    def _non_empty_parent_detail(cls, value: str | None) -> str | None:
        return _validated_optional_detail(value)


class MarkActionableOperation(BaseModel):
    type: Literal["mark_actionable"] = "mark_actionable"
    node_id: str
    reason: str = ""
    title: str | None = None
    objective: str | None = None
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @field_validator("title", "objective")
    @classmethod
    def _non_empty_root_detail(cls, value: str | None) -> str | None:
        return _validated_optional_detail(value)


class MarkBlockedOperation(BaseModel):
    type: Literal["mark_blocked"] = "mark_blocked"
    node_id: str
    reason: str = ""
    title: str | None = None
    objective: str | None = None
    missing_information: str = ""
    open_question: str = ""
    constraint_code: BlockedConstraintCode | None = None
    required_min_children: int | None = None

    @field_validator("title", "objective")
    @classmethod
    def _non_empty_root_detail(cls, value: str | None) -> str | None:
        return _validated_optional_detail(value)


class MarkOutOfScopeOperation(BaseModel):
    type: Literal["mark_out_of_scope"] = "mark_out_of_scope"
    node_id: str
    reason: str = ""
    title: str | None = None
    objective: str | None = None

    @field_validator("title", "objective")
    @classmethod
    def _non_empty_root_detail(cls, value: str | None) -> str | None:
        return _validated_optional_detail(value)


class ReviseActionableOperation(BaseModel):
    type: Literal["revise_actionable"] = "revise_actionable"
    node_id: str
    reason: str = ""
    title: str | None = None
    objective: str | None = None
    expected_outputs: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    dependencies: list[str] | None = None
    notes: list[str] | None = None
    risks: list[str] | None = None

    @field_validator("title", "objective")
    @classmethod
    def _non_empty_detail(cls, value: str | None) -> str | None:
        return _validated_optional_detail(value)


class UpdateItemOperation(BaseModel):
    """Cross-item metadata patch for related existing nodes during generation."""

    type: Literal["update_item"] = "update_item"
    node_id: str
    reason: str
    title: str | None = None
    objective: str | None = None
    dependencies: list[str] | None = None
    expected_outputs: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    notes: list[str] | None = None
    risks: list[str] | None = None
    open_questions: list[str] | None = None

    @field_validator("reason")
    @classmethod
    def _non_empty_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("title", "objective")
    @classmethod
    def _non_empty_detail(cls, value: str | None) -> str | None:
        return _validated_optional_detail(value)

    @model_validator(mode="after")
    def _requires_at_least_one_field(self) -> UpdateItemOperation:
        if any(
            value is not None
            for value in (
                self.title,
                self.objective,
                self.dependencies,
                self.expected_outputs,
                self.acceptance_criteria,
                self.notes,
                self.risks,
                self.open_questions,
            )
        ):
            return self
        raise ValueError("update_item requires at least one field to change")


PlanningOperation = Annotated[
    ExpandOperation
    | MarkActionableOperation
    | MarkBlockedOperation
    | MarkOutOfScopeOperation
    | ReviseActionableOperation,
    Field(discriminator="type"),
]


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[PlanningOperation] = Field(default_factory=list)
    updates: list[UpdateItemOperation] = Field(default_factory=list)
    plan_digest: str
    selected_items: list[str] = Field(default_factory=list)


class RunState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    active_status: RunActiveStatus = RunActiveStatus.IDLE
    iteration: int = 0
    retry_count: int = 0
    limits: PlanningLimits = Field(default_factory=PlanningLimits)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    input_digest: str = ""
    output_goal_digest: str = ""
    stop_hint_digest: str | None = None
    input_file: str = ""
    output_goal: str = ""
    last_successful_update: datetime | None = None
    agent_pids: list[int] = Field(default_factory=list)
    last_error: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class ReviewFindingSeverity(str, Enum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class RenderOutputFindingCategory(str, Enum):
    COVERAGE = "coverage"
    DEPENDENCY = "dependency"
    SCHEMA = "schema"
    CONSISTENCY = "consistency"
    CHECKLIST = "checklist"
    ACCEPTANCE = "acceptance"
    DUPLICATION = "duplication"
    OTHER = "other"


class RenderOutputReviewFinding(BaseModel):
    severity: ReviewFindingSeverity
    category: RenderOutputFindingCategory
    plan_item_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    description: str
    recommended_change: str = ""


class RenderBatchReviewDecision(str, Enum):
    APPROVE = "approve"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class RenderBatchReviewFinding(BaseModel):
    severity: ReviewFindingSeverity
    category: RenderOutputFindingCategory
    plan_item_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    description: str
    recommended_change: str = ""


class RenderBatchReviewResult(BaseModel):
    stage: Literal["render_batch_review"] = "render_batch_review"
    batch_index: int
    plan_digest: str
    output_goal_digest: str
    schedule_digest: str
    deliverable_output_digest: str
    decision: RenderBatchReviewDecision
    summary: str
    findings: list[RenderBatchReviewFinding] = Field(default_factory=list)


class RenderOutputReviewDecision(str, Enum):
    APPROVE = "approve"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class RenderedOutputReviewResult(BaseModel):
    stage: Literal["rendered_output_review"] = "rendered_output_review"
    plan_digest: str
    output_goal_digest: str
    schedule_digest: str
    deliverable_output_digest: str
    decision: RenderOutputReviewDecision
    summary: str
    findings: list[RenderOutputReviewFinding] = Field(default_factory=list)
    affected_batch_indices: list[int] = Field(default_factory=list)
    affected_artifact_paths: list[str] = Field(default_factory=list)


class ReviewFindingCategory(str, Enum):
    COVERAGE = "coverage"
    OVERLAP = "overlap"
    CONSISTENCY = "consistency"
    DEPENDENCY = "dependency"
    GRANULARITY = "granularity"
    ACCEPTANCE = "acceptance"
    SCOPE = "scope"
    OTHER = "other"


class RevisionMode(str, Enum):
    """How the orchestrator should apply a review finding."""

    REOPEN = "reopen"
    AMEND = "amend"
    ANNOTATE = "annotate"


class ReviewFinding(BaseModel):
    severity: ReviewFindingSeverity
    category: ReviewFindingCategory
    revision_mode: RevisionMode
    node_ids: list[str] = Field(default_factory=list)
    description: str
    recommended_change: str = ""


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class ConfirmationDecision(str, Enum):
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class WholePlanReviewResult(BaseModel):
    stage: Literal["whole_plan_review"] = "whole_plan_review"
    plan_digest: str
    decision: ReviewDecision
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class FinalConfirmationResult(BaseModel):
    stage: Literal["final_confirmation"] = "final_confirmation"
    plan_digest: str
    decision: ConfirmationDecision
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class ReviewStage(str, Enum):
    DECOMPOSITION = "decomposition"
    WHOLE_PLAN_REVIEW = "whole_plan_review"
    REVISION = "revision"
    FINAL_CONFIRMATION = "final_confirmation"
    RENDERING = "rendering"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class ReviewState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    stage: ReviewStage = ReviewStage.DECOMPOSITION
    plan_digest: str | None = None
    revision_cycle: int = 0
    whole_plan_review_pass: int = 0
    whole_plan_decision: ReviewDecision | None = None
    final_confirmation_decision: ConfirmationDecision | None = None
    pending_amend_node_ids: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class PlanningReport(BaseModel):
    status: FinalStatus
    review_status: ReviewStatus = ReviewStatus.PENDING
    items: int = 0
    actionable_items: int = 0
    blocked_items: int = 0
    out_of_scope_items: int = 0
    iterations: int = 0
    output_dir: str = ""
    artifacts: list[str] = Field(default_factory=list)
    summary: str | None = None
