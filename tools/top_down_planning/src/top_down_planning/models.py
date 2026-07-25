"""Typed planning state, agent contracts, and runtime models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SCHEMA_VERSION = 1
DEFAULT_CURSOR_MODEL = "auto"
DEFAULT_INLINE_EMBED_THRESHOLD = 4000


class DecompositionStatus(str, Enum):
    NEEDS_EXPANSION = "needs_expansion"
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


class RenderBatchStrategy(str, Enum):
    SINGLE = "single"
    BRANCH = "branch"
    COHERENT = "coherent"
    THROUGHPUT = "throughput"


class RenderConfig(BaseModel):
    batch_strategy: RenderBatchStrategy = RenderBatchStrategy.COHERENT
    batch_size: int = 5
    concurrent_batches: int = 3
    max_retries: int = 3
    whole_plan_context: WholePlanContextMode = WholePlanContextMode.HYBRID
    final_review: bool = True
    max_rerender_cycles: int = 2


class RenderStage(str, Enum):
    MANIFEST = "manifest"
    BATCHES = "batches"
    ASSEMBLY = "assembly"
    REVIEW = "review"
    PUBLICATION = "publication"
    COMPLETE = "complete"


class RenderBatchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VALID = "valid"
    FAILED = "failed"


class RenderOutputReviewStatus(str, Enum):
    PENDING = "pending"
    SKIPPED = "skipped"
    APPROVED = "approved"
    NEEDS_RERENDER = "needs_rerender"
    BLOCKED = "blocked"


class PublicationStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class OutputMode(str, Enum):
    SINGLE_DOCUMENT = "single_document"
    MULTI_FILE = "multi_file"


class RenderManifestItem(BaseModel):
    plan_item_id: str
    top_level_branch_id: str
    order: int
    title: str
    dependencies: list[str] = Field(default_factory=list)
    assigned_batch_id: str
    artifact_key: str
    relative_path: str | None = None
    section_order: int | None = None


class RenderManifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    plan_digest: str
    output_goal_digest: str
    render_config_digest: str
    output_mode: OutputMode = OutputMode.SINGLE_DOCUMENT
    final_relative_path: str | None = None
    items: list[RenderManifestItem] = Field(default_factory=list)


class RenderBatchArtifact(BaseModel):
    plan_item_id: str
    artifact_key: str
    relative_path: str | None = None
    section_order: int | None = None
    content: str

    @field_validator("content")
    @classmethod
    def _non_empty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty")
        return value


class RenderBatchTransaction(BaseModel):
    schema_version: int = SCHEMA_VERSION
    batch_id: str
    plan_digest: str
    output_goal_digest: str
    render_config_digest: str
    artifacts: list[RenderBatchArtifact]

    @field_validator("artifacts")
    @classmethod
    def _non_empty_artifacts(
        cls, value: list[RenderBatchArtifact]
    ) -> list[RenderBatchArtifact]:
        if not value:
            raise ValueError("artifacts must contain at least one item")
        return value


class RenderBatchStateEntry(BaseModel):
    status: RenderBatchStatus = RenderBatchStatus.PENDING
    attempts: int = 0
    transaction_digest: str | None = None
    assigned_item_ids: list[str] = Field(default_factory=list)


class RenderState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    stage: RenderStage = RenderStage.MANIFEST
    plan_digest: str = ""
    output_goal_digest: str = ""
    render_config_digest: str = ""
    render_manifest_digest: str = ""
    batches: dict[str, RenderBatchStateEntry] = Field(default_factory=dict)
    assembled_output_digest: str | None = None
    output_review_status: RenderOutputReviewStatus = RenderOutputReviewStatus.PENDING
    publication_status: PublicationStatus = PublicationStatus.PENDING
    rerender_cycle: int = 0
    updated_at: datetime | None = None


class OwnedArtifactsLedger(BaseModel):
    schema_version: int = SCHEMA_VERSION
    output_dir: str
    artifacts: list[str] = Field(default_factory=list)
    publication_digest: str | None = None


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


class Assessment(BaseModel):
    plan_complete: bool = False
    summary: str = ""


class ExpandOperation(BaseModel):
    type: Literal["expand"] = "expand"
    node_id: str
    reason: str = ""
    children: list[ChildDraft]


class MarkActionableOperation(BaseModel):
    type: Literal["mark_actionable"] = "mark_actionable"
    node_id: str
    reason: str = ""
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class MarkBlockedOperation(BaseModel):
    type: Literal["mark_blocked"] = "mark_blocked"
    node_id: str
    reason: str = ""
    missing_information: str = ""
    open_question: str = ""
    constraint_code: BlockedConstraintCode | None = None
    required_min_children: int | None = None


class MarkOutOfScopeOperation(BaseModel):
    type: Literal["mark_out_of_scope"] = "mark_out_of_scope"
    node_id: str
    reason: str = ""


class ReviseActionableOperation(BaseModel):
    type: Literal["revise_actionable"] = "revise_actionable"
    node_id: str
    reason: str = ""
    title: str | None = None
    objective: str | None = None
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


PlanningOperation = Annotated[
    ExpandOperation
    | MarkActionableOperation
    | MarkBlockedOperation
    | MarkOutOfScopeOperation
    | ReviseActionableOperation,
    Field(discriminator="type"),
]


class AgentResponse(BaseModel):
    assessment: Assessment = Field(default_factory=Assessment)
    operations: list[PlanningOperation] = Field(default_factory=list)
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
    agent_pid: int | None = None
    last_error: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_agent_pid(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "agent_pids" not in data:
            legacy_pid = data.get("agent_pid")
            data["agent_pids"] = [legacy_pid] if legacy_pid is not None else []
        return data


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
    artifact_keys: list[str] = Field(default_factory=list)
    description: str
    recommended_change: str = ""


class RenderOutputReviewDecision(str, Enum):
    APPROVE = "approve"
    NEEDS_RERENDER = "needs_rerender"
    BLOCKED = "blocked"


class RenderedOutputReviewResult(BaseModel):
    stage: Literal["rendered_output_review"] = "rendered_output_review"
    plan_digest: str
    output_goal_digest: str
    render_manifest_digest: str
    assembled_output_digest: str
    decision: RenderOutputReviewDecision
    summary: str
    findings: list[RenderOutputReviewFinding] = Field(default_factory=list)
    affected_batch_ids: list[str] = Field(default_factory=list)


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
