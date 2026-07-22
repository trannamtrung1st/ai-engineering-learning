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
    batch_size: int = 3
    concurrent_batches: int = 3
    max_retries: int = 3
    session_timeout_seconds: int = 600
    parse_error_threshold: int = 20


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


class MarkOutOfScopeOperation(BaseModel):
    type: Literal["mark_out_of_scope"] = "mark_out_of_scope"
    node_id: str
    reason: str = ""


PlanningOperation = Annotated[
    ExpandOperation
    | MarkActionableOperation
    | MarkBlockedOperation
    | MarkOutOfScopeOperation,
    Field(discriminator="type"),
]


class AgentResponse(BaseModel):
    assessment: Assessment = Field(default_factory=Assessment)
    operations: list[PlanningOperation] = Field(default_factory=list)


class RenderArtifact(BaseModel):
    """Internal fallback artifact payload written by the deterministic renderer."""

    relative_path: str
    content: str

    @field_validator("relative_path")
    @classmethod
    def _non_empty_path(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("relative_path must not be empty")
        return stripped

    @field_validator("content")
    @classmethod
    def _non_empty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty")
        return value


class RenderResponse(BaseModel):
    """Internal fallback artifact batch used by the deterministic renderer."""

    artifacts: list[RenderArtifact]

    @field_validator("artifacts")
    @classmethod
    def _non_empty_artifacts(cls, value: list[RenderArtifact]) -> list[RenderArtifact]:
        if not value:
            raise ValueError("artifacts must contain at least one item")
        return value


class RunState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    active_status: RunActiveStatus = RunActiveStatus.IDLE
    iteration: int = 0
    retry_count: int = 0
    limits: PlanningLimits = Field(default_factory=PlanningLimits)
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


class PlanningReport(BaseModel):
    status: FinalStatus
    items: int = 0
    actionable_items: int = 0
    blocked_items: int = 0
    out_of_scope_items: int = 0
    iterations: int = 0
    output_dir: str = ""
    artifacts: list[str] = Field(default_factory=list)
    summary: str | None = None
    render_fallback: bool = False
