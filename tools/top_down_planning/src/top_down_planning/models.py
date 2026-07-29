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
    CONFIRMED = "confirmed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class RunActiveStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanningLimits(BaseModel):
    max_iterations: int = 50
    max_depth: int = 6
    max_children_per_expansion: int = 12
    max_retries: int = 2
    session_timeout_seconds: int = 600
    parse_error_threshold: int = 20


class RenderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = 2
    final_review: bool = True
    max_batch_revision_cycles: int = 2
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


class ProcessedBatchRecord(BaseModel):
    """Durable record of one agent-selected planning or render batch."""

    iteration: int
    selected_items: list[str] = Field(default_factory=list)
    purpose: str = ""
    plan_digest_before: str = ""
    plan_digest_after: str = ""
    result: str = "completed"


class RenderBatchItem(BaseModel):
    """Runtime render batch selected by the agent for one authoring session."""

    batch_index: int
    item_ids: list[str]
    purpose: str = ""
    dependencies: list[str] = Field(default_factory=list)
    status: RenderBatchStatus = RenderBatchStatus.PENDING
    revision_cycle: int = 0
    title: str = ""


class RenderState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    stage: RenderStage = RenderStage.SCAFFOLD
    run_id: str = ""
    plan_digest: str = ""
    output_goal_digest: str = ""
    render_config_digest: str = ""
    current_batch_index: int = 0
    processed_batches: list[ProcessedBatchRecord] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    deliverable_output_digest: str | None = None
    output_review_status: RenderOutputReviewStatus = RenderOutputReviewStatus.PENDING
    deliverable_status: DeliverableStatus = DeliverableStatus.PENDING
    final_revision_cycle: int = 0
    scaffold_complete: bool = False
    updated_at: datetime | None = None


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_retries: int = 2


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


class PlanningMode(str, Enum):
    SIMPLE = "simple"
    LIGHTWEIGHT = "lightweight"
    FULL = "full"
    AUTO = "auto"


class ReviewCheckpoint(str, Enum):
    INITIAL_STRUCTURE = "initial_structure"
    ALL_BRANCHES_ACTIONABLE = "all_branches_actionable"
    FINAL_CANDIDATE = "final_candidate"


class ReviewerRole(str, Enum):
    COVERAGE_BOUNDARY = "coverage_boundary"
    DEPENDENCY_SEQUENCING = "dependency_sequencing"
    EXECUTABILITY_EVIDENCE = "executability_evidence"
    ADVERSARIAL = "adversarial"


class FindingDisposition(str, Enum):
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"
    ALREADY_COVERED = "already_covered"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"


class SessionStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_session: Literal["persistent"] = "persistent"
    review_checkpoints: list[ReviewCheckpoint] = Field(
        default_factory=lambda: [
            ReviewCheckpoint.INITIAL_STRUCTURE,
            ReviewCheckpoint.ALL_BRANCHES_ACTIONABLE,
            ReviewCheckpoint.FINAL_CANDIDATE,
        ]
    )
    final_adversarial_review: bool = True


class FrozenDecision(BaseModel):
    id: str
    summary: str
    rationale: str = ""
    affected_branches: list[str] = Field(default_factory=list)


class PlanningAssumption(BaseModel):
    id: str
    statement: str
    confidence: str = "assumed"


class CoverageMapping(BaseModel):
    requirement: str
    branch_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class BranchStatus(BaseModel):
    branch_id: str
    status: str
    notes: str = ""


class CrossBranchDependency(BaseModel):
    from_branch: str
    to_branch: str
    kind: str = "execution"
    notes: str = ""


class RejectedAlternative(BaseModel):
    id: str
    summary: str
    reason: str


class DiscoveredConstraint(BaseModel):
    id: str
    summary: str
    source: str = ""


class ReviewFindingSeverity(str, Enum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class ReviewFindingCategory(str, Enum):
    COVERAGE = "coverage"
    OVERLAP = "overlap"
    CONSISTENCY = "consistency"
    DEPENDENCY = "dependency"
    GRANULARITY = "granularity"
    ACCEPTANCE = "acceptance"
    SCOPE = "scope"
    OTHER = "other"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class CheckpointFinding(BaseModel):
    id: str
    severity: ReviewFindingSeverity
    category: ReviewFindingCategory
    reviewer_role: ReviewerRole
    affected_branches: list[str] = Field(default_factory=list)
    observation: str
    violated_invariant: str = ""
    recommended_disposition: str = ""
    evidence: str = ""
    checkpoint: ReviewCheckpoint | None = None


class FindingDispositionRecord(BaseModel):
    finding_id: str
    disposition: FindingDisposition
    rationale: str
    reviewer_role: ReviewerRole | None = None


class PlanningStateUpdate(BaseModel):
    """Compact delta recorded alongside a planning transaction."""

    frozen_decisions: list[FrozenDecision] = Field(default_factory=list)
    assumptions: list[PlanningAssumption] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    coverage_map: list[CoverageMapping] = Field(default_factory=list)
    branch_status: list[BranchStatus] = Field(default_factory=list)
    cross_branch_dependencies: list[CrossBranchDependency] = Field(default_factory=list)
    rejected_alternatives: list[RejectedAlternative] = Field(default_factory=list)
    discovered_constraints: list[DiscoveredConstraint] = Field(default_factory=list)
    review_findings: list[CheckpointFinding] = Field(default_factory=list)
    finding_dispositions: list[FindingDispositionRecord] = Field(default_factory=list)


class PlanningState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    frozen_decisions: list[FrozenDecision] = Field(default_factory=list)
    assumptions: list[PlanningAssumption] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    coverage_map: list[CoverageMapping] = Field(default_factory=list)
    branch_status: list[BranchStatus] = Field(default_factory=list)
    cross_branch_dependencies: list[CrossBranchDependency] = Field(default_factory=list)
    rejected_alternatives: list[RejectedAlternative] = Field(default_factory=list)
    discovered_constraints: list[DiscoveredConstraint] = Field(default_factory=list)
    review_findings: list[CheckpointFinding] = Field(default_factory=list)
    finding_dispositions: list[FindingDispositionRecord] = Field(default_factory=list)
    updated_at: datetime | None = None


class OrchestrationMetrics(BaseModel):
    primary_session_count: int = 0
    reviewer_session_count: int = 0
    branch_iterations: int = 0
    repeated_discoveries: int = 0
    findings_by_reviewer: dict[str, int] = Field(default_factory=dict)
    accepted_findings: int = 0
    rejected_findings: int = 0
    plan_rewrites: int = 0
    context_recovery_count: int = 0


class SpecialistReviewResult(BaseModel):
    stage: Literal["specialist_review"] = "specialist_review"
    reviewer_role: ReviewerRole
    plan_digest: str
    checkpoint: ReviewCheckpoint
    decision: ReviewDecision
    summary: str
    findings: list[CheckpointFinding] = Field(default_factory=list)


class DispositionResult(BaseModel):
    stage: Literal["disposition"] = "disposition"
    plan_digest: str
    reviewer_role: ReviewerRole | None = None
    checkpoint: ReviewCheckpoint | None = None
    dispositions: list[FindingDispositionRecord] = Field(default_factory=list)
    planning_state_update: PlanningStateUpdate = Field(
        default_factory=PlanningStateUpdate
    )
    summary: str = ""


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[PlanningOperation] = Field(default_factory=list)
    updates: list[UpdateItemOperation] = Field(default_factory=list)
    plan_digest: str
    selected_items: list[str] = Field(default_factory=list)
    batch_purpose: str = ""
    planning_state_update: PlanningStateUpdate | None = None

    @property
    def has_plan_changes(self) -> bool:
        return bool(self.operations or self.updates)


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    active_status: RunActiveStatus = RunActiveStatus.IDLE
    iteration: int = 0
    retry_count: int = 0
    limits: PlanningLimits = Field(default_factory=PlanningLimits)
    render: RenderConfig = Field(default_factory=RenderConfig)
    planning_model: str | None = None
    review_model: str | None = None
    rendering_model: str | None = None
    input_digest: str = ""
    output_goal_digest: str = ""
    stop_hint_digest: str | None = None
    input_file: str = ""
    output_goal: str = ""
    last_successful_update: datetime | None = None
    agent_pids: list[int] = Field(default_factory=list)
    last_error: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    processed_batches: list[ProcessedBatchRecord] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    primary_chat_id: str | None = None
    resolved_planning_mode: PlanningMode = PlanningMode.FULL
    session_strategy: SessionStrategy = Field(default_factory=SessionStrategy)
    orchestration_metrics: OrchestrationMetrics = Field(
        default_factory=OrchestrationMetrics
    )
    continuity_check_pending: bool = False
    planning_state_digest: str | None = None
    first_level_decomposed: bool = False
    all_branches_actionable: bool = False


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
    processed_batches_digest: str
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
    processed_batches_digest: str
    deliverable_output_digest: str
    decision: RenderOutputReviewDecision
    summary: str
    findings: list[RenderOutputReviewFinding] = Field(default_factory=list)
    affected_batch_indices: list[int] = Field(default_factory=list)
    affected_artifact_paths: list[str] = Field(default_factory=list)


class ReviewStage(str, Enum):
    DECOMPOSITION = "decomposition"
    CHECKPOINT = "checkpoint"
    RENDERING = "rendering"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class ReviewState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    stage: ReviewStage = ReviewStage.DECOMPOSITION
    plan_digest: str | None = None
    updated_at: datetime | None = None
    completed_checkpoints: list[str] = Field(default_factory=list)
    pending_reviewer_roles: list[str] = Field(default_factory=list)
    checkpoint_findings: list[dict[str, Any]] = Field(default_factory=list)


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
