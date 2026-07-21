"""Typed models for the todos workspace, run state, and review decisions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ItemType(str, Enum):
    FEATURE = "feature"
    FIX = "fix"
    REFACTOR = "refactor"


class ItemStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    SUPERSEDED = "superseded"


class Phase(str, Enum):
    IDLE = "idle"
    WORK = "work"
    REVIEW = "review"
    COMMIT = "commit"


class CommitState(str, Enum):
    NONE = "none"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class Transition(str, Enum):
    ATTEMPT_STARTED = "attempt_started"
    WORK_SESSION_STARTED = "work_session_started"
    WORK_SESSION_RESTARTED = "work_session_restarted"
    WORK_PHASE_READY = "work_phase_ready"
    REVIEW_SESSION_STARTED = "review_session_started"
    REVIEW_SESSION_RESTARTED = "review_session_restarted"
    REVIEW_PASSED = "review_passed"
    REVIEW_FAILED = "review_failed"
    COMMIT_STARTED = "commit_started"
    COMMIT_COMPLETED = "commit_completed"
    COMMIT_FAILED = "commit_failed"
    ITEM_DONE = "item_done"
    ITEM_BLOCKED = "item_blocked"


class ManifestSettings(BaseModel):
    max_attempts: int = 5
    max_session_restarts_per_phase: int = 2
    work_timeout_seconds: int = 1800
    review_timeout_seconds: int = 900
    auto_commit: bool = True
    stop_on_failure: bool = True
    parse_error_threshold: int = 20
    model: str | None = None

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator(
        "max_attempts",
        "max_session_restarts_per_phase",
        "work_timeout_seconds",
        "review_timeout_seconds",
        "parse_error_threshold",
    )
    @classmethod
    def positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value


class ManifestItemRef(BaseModel):
    id: str
    file: str


class Manifest(BaseModel):
    version: Literal[1] = 1
    settings: ManifestSettings = Field(default_factory=ManifestSettings)
    items: list[ManifestItemRef] = Field(default_factory=list)


class ItemResult(BaseModel):
    completed_at: datetime | None = None
    commit_sha: str | None = None
    summary: str | None = None


class ItemValidation(BaseModel):
    commands: list[str] = Field(default_factory=list)


class ItemContext(BaseModel):
    files: list[str] = Field(default_factory=list)


class TodoItem(BaseModel):
    version: Literal[1] = 1
    id: str
    title: str
    type: ItemType
    status: ItemStatus = ItemStatus.PENDING
    priority: int = 100
    depends_on: list[str] = Field(default_factory=list)
    description: str
    acceptance_criteria: list[str] = Field(min_length=1)
    validation: ItemValidation = Field(default_factory=ItemValidation)
    context: ItemContext = Field(default_factory=ItemContext)
    result: ItemResult = Field(default_factory=ItemResult)
    # Relative path of the item file within the todos workspace
    source_file: str | None = Field(default=None, exclude=True)

    @field_validator("id")
    @classmethod
    def non_empty_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id must not be empty")
        return value.strip()

    @field_validator("title", "description")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class AcceptanceCriterionResult(BaseModel):
    criterion: str
    passed: bool
    evidence: str = ""


class ValidationCommandResult(BaseModel):
    command: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""


class InstructionCompliance(BaseModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    schema_version: Literal[1] = 1
    item_id: str
    logical_attempt: int
    decision: Literal["pass", "fail", "blocked"]
    summary: str
    acceptance_criteria: list[AcceptanceCriterionResult]
    validation: list[ValidationCommandResult] = Field(default_factory=list)
    instruction_compliance: InstructionCompliance
    issues: list[str] = Field(default_factory=list)
    recommended_next_action: Literal["mark_done", "retry", "block"]

    @model_validator(mode="after")
    def consistent_decision(self) -> ReviewDecision:
        if self.decision == "pass" and self.recommended_next_action != "mark_done":
            raise ValueError("pass requires recommended_next_action=mark_done")
        if self.decision == "fail" and self.recommended_next_action != "retry":
            raise ValueError("fail requires recommended_next_action=retry")
        if self.decision == "blocked" and self.recommended_next_action != "block":
            raise ValueError("blocked requires recommended_next_action=block")
        return self


class ReviewResultRecord(BaseModel):
    decision: str | None = None
    summary: str | None = None
    issues: list[str] = Field(default_factory=list)
    raw_path: str | None = None


class RunState(BaseModel):
    schema_version: Literal[1] = 1
    item_id: str
    logical_attempt: int = 0
    phase: Phase = Phase.IDLE
    session_number: int = 0
    session_restart_count: int = 0
    last_transition: Transition | None = None
    review: ReviewResultRecord = Field(default_factory=ReviewResultRecord)
    commit_state: CommitState = CommitState.NONE
    commit_sha: str | None = None
    baseline_head: str | None = None
    work_summary: str | None = None
    last_error: str | None = None
    blocked_reason: str | None = None
    changed_paths: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime | None = None
    # Set while a detached/active Cursor agent process may still be running.
    agent_pid: int | None = None


class RestructuringProposal(BaseModel):
    """Structured proposal from a Cursor session for backlog changes."""

    schema_version: Literal[1] = 1
    item_id: str
    supersede: bool = False
    new_items: list[dict[str, Any]] = Field(default_factory=list)
    dependency_updates: dict[str, list[str]] = Field(default_factory=dict)
    notes: str = ""
