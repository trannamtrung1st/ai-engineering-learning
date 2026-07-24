"""Pre-filled review decision scaffold for session-scoped review agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from todos_tool.errors import ReviewError
from todos_tool.models import (
    EvidenceCommandResult,
    ItemStatus,
    ItemType,
    ReviewDecision,
    TodoItem,
    ValidationCommandResult,
)
from todos_tool.persistence import write_json
from todos_tool.reviewer import validate_pass

SCAFFOLD_FILENAME = "review-scaffold.json"


@dataclass(frozen=True)
class ReviewScaffold:
    schema_version: int
    item_id: str
    logical_attempt: int
    acceptance_criteria: list[str]
    allow_empty_commit: bool
    authoritative_validation: list[ValidationCommandResult]
    authoritative_evidence: list[EvidenceCommandResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "logical_attempt": self.logical_attempt,
            "acceptance_criteria": list(self.acceptance_criteria),
            "allow_empty_commit": self.allow_empty_commit,
            "authoritative_validation": [
                result.to_dict() for result in self.authoritative_validation
            ],
            "authoritative_evidence": [
                result.to_dict() for result in self.authoritative_evidence
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewScaffold:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            item_id=str(data["item_id"]),
            logical_attempt=int(data["logical_attempt"]),
            acceptance_criteria=[str(entry) for entry in data["acceptance_criteria"]],
            allow_empty_commit=bool(data.get("allow_empty_commit", True)),
            authoritative_validation=[
                ValidationCommandResult.from_dict(entry)
                for entry in data.get("authoritative_validation", [])
            ],
            authoritative_evidence=[
                EvidenceCommandResult.from_dict(entry)
                for entry in data.get("authoritative_evidence", [])
            ],
        )

    def decision_template(self) -> dict[str, Any]:
        """Return a fill-in review decision with exact criterion strings."""
        template: dict[str, Any] = {
            "schema_version": 1,
            "item_id": self.item_id,
            "logical_attempt": self.logical_attempt,
            "decision": "pass",
            "summary": "",
            "acceptance_criteria": [
                {"criterion": criterion, "passed": True, "evidence": ""}
                for criterion in self.acceptance_criteria
            ],
            "validation": [
                {
                    "command": result.command,
                    "passed": result.passed,
                    "exit_code": result.exit_code,
                    "summary": result.summary,
                }
                for result in self.authoritative_validation
            ],
            "instruction_compliance": {"passed": True, "violations": []},
            "issues": [],
            "recommended_next_action": "mark_done",
        }
        if self.authoritative_evidence:
            template["evidence"] = [
                {
                    "command": result.command,
                    "cwd": result.cwd,
                    "passed": result.passed,
                    "exit_code": result.exit_code,
                    "summary": result.summary,
                }
                for result in self.authoritative_evidence
            ]
        if self.allow_empty_commit:
            template["proposed_commit_message"] = None
        else:
            template["proposed_commit_message"] = ""
        return template

    def to_item(self) -> TodoItem:
        return TodoItem(
            id=self.item_id,
            title=self.item_id,
            type=ItemType.FEATURE,
            status=ItemStatus.IN_PROGRESS,
            description="",
            acceptance_criteria=list(self.acceptance_criteria),
            allow_empty_commit=self.allow_empty_commit,
        )


def review_scaffold_path(attempt_dir: Path) -> Path:
    return attempt_dir / SCAFFOLD_FILENAME


def build_review_scaffold(
    item: TodoItem,
    *,
    logical_attempt: int,
    authoritative_validation: list[ValidationCommandResult],
    authoritative_evidence: list[EvidenceCommandResult] | None = None,
) -> ReviewScaffold:
    return ReviewScaffold(
        schema_version=1,
        item_id=item.id,
        logical_attempt=logical_attempt,
        acceptance_criteria=list(item.acceptance_criteria),
        allow_empty_commit=item.allow_empty_commit,
        authoritative_validation=list(authoritative_validation),
        authoritative_evidence=list(authoritative_evidence or []),
    )


def write_review_scaffold(path: Path, scaffold: ReviewScaffold) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, scaffold.to_dict())


def load_review_scaffold(path: Path) -> ReviewScaffold:
    if not path.is_file():
        raise ReviewError(f"Review scaffold not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Invalid review scaffold {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError(f"Review scaffold must be a JSON object: {path}")
    return ReviewScaffold.from_dict(data)


def validate_review_decision(
    scaffold: ReviewScaffold,
    decision: ReviewDecision,
) -> None:
    validate_pass(
        decision,
        scaffold.to_item(),
        scaffold.logical_attempt,
        scaffold.authoritative_validation,
        scaffold.authoritative_evidence,
    )
