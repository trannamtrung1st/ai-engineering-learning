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


class RenderTraversal(str, Enum):
    BREADTH_FIRST = "breadth_first"


class RenderScope(str, Enum):
    ALL_NODES = "all_nodes"
    ACTIONABLE_NODES = "actionable_nodes"


class FinalSynthesisMode(str, Enum):
    OPTIONAL = "optional"
    REQUIRED = "required"


class RollupConfig(BaseModel):
    enabled: bool = False


class RenderConfig(BaseModel):
    dry_run: bool = False
    batch_size: int = 5
    concurrent_batches: int = 3
    max_retries: int = 3
    whole_plan_context: WholePlanContextMode = WholePlanContextMode.HYBRID
    final_review: bool = True
    max_rerender_cycles: int = 2
    traversal: RenderTraversal = RenderTraversal.BREADTH_FIRST
    scope: RenderScope = RenderScope.ALL_NODES
    allow_final_publication: bool = True
    allow_staged_artifacts: bool = True
    final_synthesis: FinalSynthesisMode = FinalSynthesisMode.OPTIONAL
    rollup: RollupConfig = Field(default_factory=RollupConfig)


class RenderStage(str, Enum):
    MANIFEST = "manifest"
    WAVES = "waves"
    REVIEW = "review"
    FINALIZATION = "finalization"
    COMPLETE = "complete"


class RenderOutputReviewStatus(str, Enum):
    PENDING = "pending"
    SKIPPED = "skipped"
    APPROVED = "approved"
    NEEDS_RERENDER = "needs_rerender"
    BLOCKED = "blocked"


class DeliverableStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class RenderDecisionKind(str, Enum):
    PRODUCE = "produce"
    SKIP = "skip"
    DEFER = "defer"


class RenderNodePhase(str, Enum):
    RENDER = "render"
    ROLLUP = "rollup"


class DeferredToKind(str, Enum):
    NODE = "node"
    PHASE = "phase"


class DeferredTo(BaseModel):
    kind: DeferredToKind
    id: str
    phase: RenderNodePhase | None = None


class ArtifactLocation(str, Enum):
    FINAL = "final"
    STAGED = "staged"


class ArtifactOperation(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class OwnerKind(str, Enum):
    NODE = "node"
    PHASE = "phase"


class ArtifactIntent(BaseModel):
    artifact_key: str
    path: str
    location: ArtifactLocation
    operation: ArtifactOperation
    owner_kind: OwnerKind
    owner_id: str
    content_digest: str | None = None
    prior_content_digest: str | None = None


class OwnershipChange(BaseModel):
    path: str
    prior_owner_kind: OwnerKind
    prior_owner_id: str
    new_owner_kind: OwnerKind
    new_owner_id: str


class RenderDecisionRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    decision_id: str
    node_id: str
    phase: RenderNodePhase = RenderNodePhase.RENDER
    revision: int = 1
    supersedes: str | None = None
    plan_digest: str
    decision: RenderDecisionKind
    reason: str = ""
    deferred_to: DeferredTo | None = None
    resolves: list[str] = Field(default_factory=list)
    context_digest: str = ""
    read_set_digest: str = ""
    commit_sequence: int | None = None
    artifacts: list[ArtifactIntent] = Field(default_factory=list)
    ownership_changes: list[OwnershipChange] = Field(default_factory=list)
    committed_at: str | None = None


class PhaseType(str, Enum):
    SYNTHESIS = "synthesis"
    ROLLUP = "rollup"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    INVALIDATED = "invalidated"
    FAILED = "failed"


class PhaseCompletionRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    phase_id: str
    phase_type: PhaseType
    status: PhaseStatus = PhaseStatus.PENDING
    revision: int = 1
    supersedes: str | None = None
    resolves: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    commit_sequence: int | None = None
    committed_at: str | None = None


class NodeRenderRevisionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUBMITTED = "submitted"
    COMMITTED = "committed"
    INVALIDATED = "invalidated"
    FAILED = "failed"
    DEPENDENCY_FAILED = "dependency_failed"


class NodeRenderRevision(BaseModel):
    status: NodeRenderRevisionStatus = NodeRenderRevisionStatus.PENDING
    state_id: str | None = None
    decision: RenderDecisionKind | None = None
    decision_id: str | None = None
    decision_digest: str | None = None
    attempts: int = 0
    artifacts: list[str] = Field(default_factory=list)


class NodeRenderPhaseState(BaseModel):
    current_revision: int = 1
    revisions: dict[int, NodeRenderRevision] = Field(default_factory=dict)


class RenderManifestItemStatus(str, Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"
    FAILED = "failed"
    DEPENDENCY_FAILED = "dependency_failed"


class RenderManifestItem(BaseModel):
    plan_item_id: str
    parent_id: str | None = None
    depth: int = 0
    order: int = 1
    wave: int = 0
    generation_group: int = 0
    assigned_wave_id: str = ""
    phase: RenderNodePhase = RenderNodePhase.RENDER
    revision: int = 1
    decision_path: str | None = None
    status: RenderManifestItemStatus = RenderManifestItemStatus.PENDING
    title: str = ""
    dependencies: list[str] = Field(default_factory=list)
    top_level_branch_id: str = ""


class RenderManifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    plan_digest: str
    output_goal_digest: str
    render_config_digest: str
    items: list[RenderManifestItem] = Field(default_factory=list)


class RenderState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    stage: RenderStage = RenderStage.MANIFEST
    run_id: str = ""
    plan_digest: str = ""
    output_goal_digest: str = ""
    render_config_digest: str = ""
    render_manifest_digest: str = ""
    commit_sequence: int = 0
    nodes: dict[str, dict[str, NodeRenderPhaseState]] = Field(default_factory=dict)
    deliverable_output_digest: str | None = None
    output_review_status: RenderOutputReviewStatus = RenderOutputReviewStatus.PENDING
    deliverable_status: DeliverableStatus = DeliverableStatus.PENDING
    rerender_cycle: int = 0
    updated_at: datetime | None = None


class OwnershipLedgerEntryState(str, Enum):
    ACTIVE = "active"
    DELETED = "deleted"


class OwnershipLedgerEntry(BaseModel):
    location: ArtifactLocation
    state: OwnershipLedgerEntryState = OwnershipLedgerEntryState.ACTIVE
    owner_kind: OwnerKind
    owner_id: str
    artifact_key: str
    content_digest: str | None = None
    prior_content_digest: str | None = None
    last_transaction_id: str | None = None
    commit_sequence: int | None = None
    deleting_decision_id: str | None = None


class OwnershipLedger(BaseModel):
    schema_version: int = SCHEMA_VERSION
    artifacts: dict[str, OwnershipLedgerEntry] = Field(default_factory=dict)


class CoordinatorState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    workspace_generation: int = 0
    active_run_id: str | None = None
    frozen_for_review: bool = False


class CommitJournalEntryStatus(str, Enum):
    PREPARED = "prepared"
    PUBLISHING = "publishing"
    COMMITTED = "committed"
    ABORTED = "aborted"


class CommitJournalEntry(BaseModel):
    transaction_id: str
    manifest_slot: int
    node_id: str | None = None
    phase_id: str | None = None
    status: CommitJournalEntryStatus = CommitJournalEntryStatus.PREPARED
    workspace_generation: int = 0
    decision_id: str | None = None
    published_paths: list[str] = Field(default_factory=list)
    payload_digest: str = ""


class RenderContextSnapshot(BaseModel):
    context_digest: str
    read_set_digest: str
    plan_digest: str
    node_id: str
    phase: RenderNodePhase = RenderNodePhase.RENDER
    ancestor_decision_ids: list[str] = Field(default_factory=list)
    dependency_decision_ids: list[str] = Field(default_factory=list)
    owned_artifact_paths: list[str] = Field(default_factory=list)


class RenderNodeTransaction(BaseModel):
    schema_version: int = SCHEMA_VERSION
    transaction_id: str
    node_id: str
    phase: RenderNodePhase = RenderNodePhase.RENDER
    revision: int = 1
    context_digest: str
    read_set_digest: str
    plan_digest: str
    output_goal_digest: str
    render_config_digest: str
    decision: RenderDecisionKind | None = None
    reason: str = ""
    deferred_to: DeferredTo | None = None
    resolves: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactIntent] = Field(default_factory=list)
    ownership_changes: list[OwnershipChange] = Field(default_factory=list)
    staged_files: dict[str, str] = Field(default_factory=dict)


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
    deliverable_output_digest: str
    decision: RenderOutputReviewDecision
    summary: str
    findings: list[RenderOutputReviewFinding] = Field(default_factory=list)
    affected_node_ids: list[str] = Field(default_factory=list)


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
