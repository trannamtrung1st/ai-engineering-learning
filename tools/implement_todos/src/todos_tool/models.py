"""Typed models for the todos workspace, run state, and review decisions."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from todos_tool.paths import validate_item_id as _validate_item_id


DEFAULT_CURSOR_MODEL = "composer-2.5"


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


class ProvenanceKind(str, Enum):
    DRIVER = "driver"
    EXTERNAL = "external"
    SKIPPED = "skipped"


class Transition(str, Enum):
    ATTEMPT_STARTED = "attempt_started"
    WORK_SESSION_STARTED = "work_session_started"
    WORK_SESSION_RESTARTED = "work_session_restarted"
    WORK_PHASE_READY = "work_phase_ready"
    WORK_PHASE_FAILED = "work_phase_failed"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    REVIEW_SESSION_STARTED = "review_session_started"
    REVIEW_SESSION_RESTARTED = "review_session_restarted"
    REVIEW_PASSED = "review_passed"
    REVIEW_FAILED = "review_failed"
    COMMIT_STARTED = "commit_started"
    COMMIT_COMPLETED = "commit_completed"
    COMMIT_FAILED = "commit_failed"
    ITEM_DONE = "item_done"
    ITEM_BLOCKED = "item_blocked"


def _require_mapping(data: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a mapping")
    return data


def _require_str(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _optional_str(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    text = _require_str(value, label=label).strip()
    return text or None


def _parse_enum(enum_cls: type[Enum], value: Any, *, label: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"{label} has invalid value {value!r}") from exc
    raise ValueError(f"{label} must be a {enum_cls.__name__}")


def _parse_datetime(value: Any, *, label: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    raise ValueError(f"{label} must be an ISO-8601 timestamp")


def _parse_str_list(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    items: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{label}[{idx}] must be a string")
        items.append(item)
    return items


def _positive_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if value < 1:
        raise ValueError(f"{label} must be >= 1")
    return value


def _non_negative_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if value < 0:
        raise ValueError(f"{label} must be >= 0")
    return value


@dataclass
class ManifestSettings:
    max_attempts: int = 5
    max_session_restarts_per_phase: int = 2
    max_validation_repairs_per_attempt: int = 2
    work_timeout_seconds: int = 1800
    review_timeout_seconds: int = 900
    validation_timeout_seconds: int = 900
    auto_commit: bool = True
    stop_on_failure: bool = True
    parse_error_threshold: int = 20
    model: str | None = DEFAULT_CURSOR_MODEL
    project_check: str | None = None

    def __post_init__(self) -> None:
        if self.model is not None:
            stripped = self.model.strip()
            self.model = stripped or None
        if self.project_check is not None:
            stripped = self.project_check.strip()
            if not stripped:
                raise ValueError("project_check must not be empty when present")
            self.project_check = stripped

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestSettings:
        mapping = _require_mapping(data, label="settings")
        unknown = set(mapping) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown settings fields: {sorted(unknown)}")
        if "project_check" in mapping:
            raw_pc = mapping["project_check"]
            if isinstance(raw_pc, str) and not raw_pc.strip():
                raise ValueError("project_check must not be empty")
            project_check = _optional_str(raw_pc, label="project_check")
        else:
            project_check = None
        return cls(
            max_attempts=_positive_int(
                mapping.get("max_attempts", 5), label="max_attempts"
            ),
            max_session_restarts_per_phase=_positive_int(
                mapping.get("max_session_restarts_per_phase", 2),
                label="max_session_restarts_per_phase",
            ),
            max_validation_repairs_per_attempt=_non_negative_int(
                mapping.get("max_validation_repairs_per_attempt", 2),
                label="max_validation_repairs_per_attempt",
            ),
            work_timeout_seconds=_positive_int(
                mapping.get("work_timeout_seconds", 1800),
                label="work_timeout_seconds",
            ),
            review_timeout_seconds=_positive_int(
                mapping.get("review_timeout_seconds", 900),
                label="review_timeout_seconds",
            ),
            validation_timeout_seconds=_positive_int(
                mapping.get("validation_timeout_seconds", 900),
                label="validation_timeout_seconds",
            ),
            auto_commit=bool(mapping.get("auto_commit", True)),
            stop_on_failure=bool(mapping.get("stop_on_failure", True)),
            parse_error_threshold=_positive_int(
                mapping.get("parse_error_threshold", 20),
                label="parse_error_threshold",
            ),
            model=_optional_str(
                mapping.get("model", DEFAULT_CURSOR_MODEL),
                label="model",
            ),
            project_check=project_check,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "max_session_restarts_per_phase": self.max_session_restarts_per_phase,
            "max_validation_repairs_per_attempt": self.max_validation_repairs_per_attempt,
            "work_timeout_seconds": self.work_timeout_seconds,
            "review_timeout_seconds": self.review_timeout_seconds,
            "validation_timeout_seconds": self.validation_timeout_seconds,
            "auto_commit": self.auto_commit,
            "stop_on_failure": self.stop_on_failure,
            "parse_error_threshold": self.parse_error_threshold,
            "model": self.model,
            "project_check": self.project_check,
        }

    @classmethod
    def model_validate(cls, data: Any) -> ManifestSettings:
        return cls.from_dict(_require_mapping(data, label="settings"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ManifestItemRef:
    id: str
    file: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestItemRef:
        mapping = _require_mapping(data, label="manifest item")
        unknown = set(mapping) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown manifest item fields: {sorted(unknown)}")
        return cls(
            id=_validate_item_id(_require_str(mapping["id"], label="id")),
            file=_require_str(mapping["file"], label="file"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "file": self.file}

    @classmethod
    def model_validate(cls, data: Any) -> ManifestItemRef:
        return cls.from_dict(_require_mapping(data, label="manifest item"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class Manifest:
    settings: ManifestSettings
    version: Literal[1] = 1
    items: list[ManifestItemRef] = field(default_factory=list)
    authority: list[str] | None = None
    hard_rules: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        validate_manifest(data)
        mapping = _require_mapping(data, label="manifest")
        version = mapping.get("version", 1)
        if version != 1:
            raise ValueError("manifest version must be 1")
        authority_raw = mapping.get("authority")
        authority: list[str] | None = None
        if authority_raw is not None:
            authority = _parse_str_list(authority_raw, label="authority")
        return cls(
            version=1,
            settings=ManifestSettings.from_dict(mapping["settings"]),
            items=[
                ManifestItemRef.from_dict(item)
                for item in mapping.get("items") or []
            ],
            authority=authority,
            hard_rules=_parse_str_list(
                mapping.get("hard_rules"), label="hard_rules"
            ),
            stop_conditions=_parse_str_list(
                mapping.get("stop_conditions"), label="stop_conditions"
            ),
            out_of_scope=_parse_str_list(
                mapping.get("out_of_scope"), label="out_of_scope"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "settings": self.settings.to_dict(),
            "items": [item.to_dict() for item in self.items],
        }
        if self.authority is not None:
            payload["authority"] = list(self.authority)
        if self.hard_rules:
            payload["hard_rules"] = list(self.hard_rules)
        if self.stop_conditions:
            payload["stop_conditions"] = list(self.stop_conditions)
        if self.out_of_scope:
            payload["out_of_scope"] = list(self.out_of_scope)
        return payload

    @classmethod
    def model_validate(cls, data: Any) -> Manifest:
        return cls.from_dict(_require_mapping(data, label="manifest"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


def validate_manifest(data: dict[str, Any]) -> None:
    """Raise ValueError when manifest data is invalid."""
    mapping = _require_mapping(data, label="manifest")
    unknown = set(mapping) - {
        "version",
        "settings",
        "items",
        "authority",
        "hard_rules",
        "stop_conditions",
        "out_of_scope",
    }
    if unknown:
        raise ValueError(f"Unknown manifest fields: {sorted(unknown)}")
    version = mapping.get("version", 1)
    if version != 1:
        raise ValueError("manifest version must be 1")
    if "settings" not in mapping:
        raise ValueError("manifest.settings is required")
    ManifestSettings.from_dict(mapping["settings"])
    items = mapping.get("items")
    if items is None:
        return
    if not isinstance(items, list):
        raise ValueError("manifest.items must be a list")
    for idx, item in enumerate(items):
        ManifestItemRef.from_dict(_require_mapping(item, label=f"items[{idx}]"))


@dataclass
class ItemResult:
    completed_at: datetime | None = None
    commit_sha: str | None = None
    summary: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ItemResult:
        if data is None:
            return cls()
        mapping = _require_mapping(data, label="result")
        return cls(
            completed_at=_parse_datetime(
                mapping.get("completed_at"), label="result.completed_at"
            ),
            commit_sha=_optional_str(
                mapping.get("commit_sha"), label="result.commit_sha"
            ),
            summary=_optional_str(mapping.get("summary"), label="result.summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at is not None else None
            ),
            "commit_sha": self.commit_sha,
            "summary": self.summary,
        }
        return payload

    @classmethod
    def model_validate(cls, data: Any) -> ItemResult:
        if data is None:
            return cls()
        return cls.from_dict(_require_mapping(data, label="result"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ItemValidation:
    commands: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ItemValidation:
        if data is None:
            return cls()
        mapping = _require_mapping(data, label="validation")
        return cls(commands=_parse_str_list(mapping.get("commands"), label="commands"))

    def to_dict(self) -> dict[str, Any]:
        return {"commands": list(self.commands)}

    @classmethod
    def model_validate(cls, data: Any) -> ItemValidation:
        if data is None:
            return cls()
        return cls.from_dict(_require_mapping(data, label="validation"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ItemEvidence:
    commands: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ItemEvidence:
        if data is None:
            return cls()
        mapping = _require_mapping(data, label="evidence")
        return cls(commands=_parse_str_list(mapping.get("commands"), label="commands"))

    def to_dict(self) -> dict[str, Any]:
        return {"commands": list(self.commands)}

    @classmethod
    def model_validate(cls, data: Any) -> ItemEvidence:
        if data is None:
            return cls()
        return cls.from_dict(_require_mapping(data, label="evidence"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ItemContext:
    files: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ItemContext:
        if data is None:
            return cls()
        mapping = _require_mapping(data, label="context")
        return cls(files=_parse_str_list(mapping.get("files"), label="files"))

    def to_dict(self) -> dict[str, Any]:
        return {"files": list(self.files)}

    @classmethod
    def model_validate(cls, data: Any) -> ItemContext:
        if data is None:
            return cls()
        return cls.from_dict(_require_mapping(data, label="context"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ChecklistItem:
    id: str
    text: str
    done: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChecklistItem:
        mapping = _require_mapping(data, label="checklist item")
        unknown = set(mapping) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown checklist item fields: {sorted(unknown)}")
        return cls(
            id=_require_str(mapping["id"], label="checklist.id").strip(),
            text=_require_str(mapping["text"], label="checklist.text").strip(),
            done=bool(mapping.get("done", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "done": self.done}

    @classmethod
    def model_validate(cls, data: Any) -> ChecklistItem:
        return cls.from_dict(_require_mapping(data, label="checklist item"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class TodoItem:
    id: str
    title: str
    type: ItemType
    description: str
    acceptance_criteria: list[str]
    version: Literal[1] = 1
    status: ItemStatus = ItemStatus.PENDING
    priority: int = 100
    depends_on: list[str] = field(default_factory=list)
    validation: ItemValidation = field(default_factory=ItemValidation)
    evidence: ItemEvidence = field(default_factory=ItemEvidence)
    context: ItemContext = field(default_factory=ItemContext)
    result: ItemResult = field(default_factory=ItemResult)
    contract_refs: list[str] = field(default_factory=list)
    checklist: list[ChecklistItem] = field(default_factory=list)
    source_file: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.type, str):
            self.type = ItemType(self.type)
        if isinstance(self.status, str):
            self.status = ItemStatus(self.status)
        if isinstance(self.validation, dict):
            self.validation = ItemValidation.from_dict(self.validation)
        if isinstance(self.evidence, dict):
            self.evidence = ItemEvidence.from_dict(self.evidence)
        if isinstance(self.context, dict):
            self.context = ItemContext.from_dict(self.context)
        if isinstance(self.result, dict):
            self.result = ItemResult.from_dict(self.result)
        if self.checklist and isinstance(self.checklist[0], dict):
            self.checklist = [
                ChecklistItem.from_dict(entry) if isinstance(entry, dict) else entry
                for entry in self.checklist
            ]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        validate_todo_item(data)
        mapping = _require_mapping(data, label="item")
        return cls(
            version=1,
            id=_validate_item_id(_require_str(mapping["id"], label="id")),
            title=_require_str(mapping["title"], label="title"),
            type=_parse_enum(ItemType, mapping["type"], label="type"),  # type: ignore[arg-type]
            status=_parse_enum(
                ItemStatus, mapping.get("status", ItemStatus.PENDING.value), label="status"
            ),  # type: ignore[arg-type]
            priority=int(mapping.get("priority", 100)),
            depends_on=_parse_str_list(mapping.get("depends_on"), label="depends_on"),
            description=_require_str(mapping["description"], label="description"),
            acceptance_criteria=_parse_str_list(
                mapping["acceptance_criteria"], label="acceptance_criteria"
            ),
            validation=ItemValidation.from_dict(mapping.get("validation")),
            evidence=ItemEvidence.from_dict(mapping.get("evidence")),
            context=ItemContext.from_dict(mapping.get("context")),
            result=ItemResult.from_dict(mapping.get("result")),
            contract_refs=_parse_str_list(
                mapping.get("contract_refs"), label="contract_refs"
            ),
            checklist=[
                ChecklistItem.from_dict(entry)
                for entry in mapping.get("checklist") or []
            ],
            source_file=_optional_str(mapping.get("source_file"), label="source_file"),
        )

    def to_dict(self, *, include_source_file: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "status": self.status.value,
            "priority": self.priority,
            "depends_on": list(self.depends_on),
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "validation": self.validation.to_dict(),
            "context": self.context.to_dict(),
            "result": self.result.to_dict(),
        }
        if self.evidence.commands:
            payload["evidence"] = self.evidence.to_dict()
        if self.contract_refs:
            payload["contract_refs"] = list(self.contract_refs)
        if self.checklist:
            payload["checklist"] = [entry.to_dict() for entry in self.checklist]
        if include_source_file and self.source_file is not None:
            payload["source_file"] = self.source_file
        return payload

    @classmethod
    def model_validate(cls, data: Any) -> TodoItem:
        return cls.from_dict(_require_mapping(data, label="item"))

    def model_dump(
        self,
        mode: str = "json",
        *,
        exclude_none: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        data = self.to_dict(include_source_file=self.source_file is not None)
        if exclude_none:
            return {key: value for key, value in data.items() if value is not None}
        return data

    def model_copy(self, *, deep: bool = False) -> TodoItem:
        if deep:
            return TodoItem.from_dict(
                self.to_dict(include_source_file=self.source_file is not None)
            )
        from dataclasses import replace

        return replace(self)


def validate_todo_item(data: dict[str, Any]) -> None:
    """Raise ValueError when todo item data is invalid."""
    mapping = _require_mapping(data, label="item")
    unknown = set(mapping) - {
        "version",
        "id",
        "title",
        "type",
        "status",
        "priority",
        "depends_on",
        "description",
        "acceptance_criteria",
        "validation",
        "evidence",
        "context",
        "result",
        "contract_refs",
        "checklist",
        "source_file",
    }
    if unknown:
        raise ValueError(f"Unknown item fields: {sorted(unknown)}")
    version = mapping.get("version", 1)
    if version != 1:
        raise ValueError("item version must be 1")
    for label in ("id", "title", "description"):
        if label not in mapping:
            raise ValueError(f"item.{label} is required")
        if not _require_str(mapping[label], label=label).strip():
            raise ValueError(f"item.{label} must not be empty")
    _validate_item_id(_require_str(mapping["id"], label="id"))
    _parse_enum(ItemType, mapping["type"], label="type")
    if "acceptance_criteria" not in mapping:
        raise ValueError("item.acceptance_criteria is required")
    criteria = _parse_str_list(
        mapping["acceptance_criteria"], label="acceptance_criteria"
    )
    if not criteria:
        raise ValueError("item.acceptance_criteria must contain at least one entry")
    ItemValidation.from_dict(mapping.get("validation"))
    ItemEvidence.from_dict(mapping.get("evidence"))
    ItemContext.from_dict(mapping.get("context"))
    ItemResult.from_dict(mapping.get("result"))
    checklist = mapping.get("checklist")
    if checklist is not None:
        if not isinstance(checklist, list):
            raise ValueError("item.checklist must be a list")
        for idx, entry in enumerate(checklist):
            item = ChecklistItem.from_dict(_require_mapping(entry, label=f"checklist[{idx}]"))
            if not item.id:
                raise ValueError(f"checklist[{idx}].id must not be empty")
            if not item.text:
                raise ValueError(f"checklist[{idx}].text must not be empty")


@dataclass
class AcceptanceCriterionResult:
    criterion: str
    passed: bool
    evidence: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcceptanceCriterionResult:
        mapping = _require_mapping(data, label="acceptance criterion result")
        return cls(
            criterion=_require_str(mapping["criterion"], label="criterion"),
            passed=bool(mapping["passed"]),
            evidence=_require_str(mapping.get("evidence", ""), label="evidence"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "passed": self.passed,
            "evidence": self.evidence,
        }

    @classmethod
    def model_validate(cls, data: Any) -> AcceptanceCriterionResult:
        return cls.from_dict(_require_mapping(data, label="acceptance criterion result"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ValidationCommandResult:
    command: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationCommandResult:
        mapping = _require_mapping(data, label="validation command result")
        exit_code = mapping.get("exit_code")
        if exit_code is not None and not isinstance(exit_code, int):
            raise ValueError("exit_code must be an integer")
        return cls(
            command=_require_str(mapping["command"], label="command"),
            passed=bool(mapping["passed"]),
            exit_code=exit_code,
            summary=_require_str(mapping.get("summary", ""), label="summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "summary": self.summary,
        }

    @classmethod
    def model_validate(cls, data: Any) -> ValidationCommandResult:
        return cls.from_dict(_require_mapping(data, label="validation command result"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class InstructionCompliance:
    passed: bool
    violations: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstructionCompliance:
        mapping = _require_mapping(data, label="instruction_compliance")
        return cls(
            passed=bool(mapping["passed"]),
            violations=_parse_str_list(mapping.get("violations"), label="violations"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "violations": list(self.violations)}

    @classmethod
    def model_validate(cls, data: Any) -> InstructionCompliance:
        return cls.from_dict(_require_mapping(data, label="instruction_compliance"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ReviewIssue:
    """Structured or legacy review note."""

    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    title: str = ""
    detail: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.severity in ("medium", "high", "critical")

    def display(self) -> str:
        body = self.title.strip()
        if self.detail.strip():
            body = f"{body}: {self.detail.strip()}" if body else self.detail.strip()
        if not body:
            return ""
        return f"[{self.severity}] {body}"

    @classmethod
    def coerce(cls, value: Any) -> ReviewIssue:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return cls(severity="info", title="", detail="")
            return cls(severity="medium", title=text, detail="")
        if isinstance(value, dict):
            severity = value.get("severity", "medium")
            if severity not in ("info", "low", "medium", "high", "critical"):
                severity = "medium"
            return cls(
                severity=severity,
                title=str(value.get("title", "") or ""),
                detail=str(value.get("detail", "") or ""),
            )
        raise ValueError(f"Unsupported review issue: {value!r}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewIssue:
        return cls.coerce(data)

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "title": self.title, "detail": self.detail}

    @classmethod
    def model_validate(cls, data: Any) -> ReviewIssue:
        return cls.coerce(data)

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ReviewDecision:
    item_id: str
    logical_attempt: int
    decision: Literal["pass", "fail", "blocked"]
    summary: str
    acceptance_criteria: list[AcceptanceCriterionResult]
    instruction_compliance: InstructionCompliance
    schema_version: Literal[1] = 1
    validation: list[ValidationCommandResult] = field(default_factory=list)
    issues: list[ReviewIssue] = field(default_factory=list)
    recommended_next_action: Literal["mark_done", "retry", "block"] = "retry"

    def __post_init__(self) -> None:
        if self.issues and not isinstance(self.issues[0], ReviewIssue):
            self.issues = [ReviewIssue.coerce(item) for item in self.issues]
        self._validate_consistency()

    def _validate_consistency(self) -> None:
        if self.decision == "pass" and self.recommended_next_action != "mark_done":
            raise ValueError("pass requires recommended_next_action=mark_done")
        if self.decision == "fail" and self.recommended_next_action != "retry":
            raise ValueError("fail requires recommended_next_action=retry")
        if self.decision == "blocked" and self.recommended_next_action != "block":
            raise ValueError("blocked requires recommended_next_action=block")

    def issue_strings(self) -> list[str]:
        return [text for issue in self.issues if (text := issue.display())]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewDecision:
        mapping = _require_mapping(data, label="review decision")
        issues_raw = mapping.get("issues")
        issues: list[ReviewIssue] = []
        if issues_raw is not None:
            if not isinstance(issues_raw, list):
                raise ValueError("issues must be a list")
            issues = [ReviewIssue.coerce(item) for item in issues_raw]
        return cls(
            schema_version=1,
            item_id=_require_str(mapping["item_id"], label="item_id"),
            logical_attempt=int(mapping["logical_attempt"]),
            decision=mapping["decision"],  # type: ignore[arg-type]
            summary=_require_str(mapping["summary"], label="summary"),
            acceptance_criteria=[
                AcceptanceCriterionResult.from_dict(entry)
                for entry in mapping["acceptance_criteria"]
            ],
            validation=[
                ValidationCommandResult.from_dict(entry)
                for entry in mapping.get("validation") or []
            ],
            instruction_compliance=InstructionCompliance.from_dict(
                mapping["instruction_compliance"]
            ),
            issues=issues,
            recommended_next_action=mapping["recommended_next_action"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "logical_attempt": self.logical_attempt,
            "decision": self.decision,
            "summary": self.summary,
            "acceptance_criteria": [
                entry.to_dict() for entry in self.acceptance_criteria
            ],
            "validation": [entry.to_dict() for entry in self.validation],
            "instruction_compliance": self.instruction_compliance.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "recommended_next_action": self.recommended_next_action,
        }

    @classmethod
    def model_validate(cls, data: Any) -> ReviewDecision:
        return cls.from_dict(_require_mapping(data, label="review decision"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class ReviewResultRecord:
    decision: str | None = None
    summary: str | None = None
    issues: list[str] = field(default_factory=list)
    raw_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReviewResultRecord:
        if data is None:
            return cls()
        mapping = _require_mapping(data, label="review")
        return cls(
            decision=_optional_str(mapping.get("decision"), label="decision"),
            summary=_optional_str(mapping.get("summary"), label="summary"),
            issues=_parse_str_list(mapping.get("issues"), label="issues"),
            raw_path=_optional_str(mapping.get("raw_path"), label="raw_path"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "summary": self.summary,
            "issues": list(self.issues),
            "raw_path": self.raw_path,
        }

    @classmethod
    def model_validate(cls, data: Any) -> ReviewResultRecord:
        if data is None:
            return cls()
        return cls.from_dict(_require_mapping(data, label="review"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class RunState:
    item_id: str
    schema_version: Literal[1] = 1
    logical_attempt: int = 0
    phase: Phase = Phase.IDLE
    session_number: int = 0
    session_restart_count: int = 0
    last_transition: Transition | None = None
    review: ReviewResultRecord = field(default_factory=ReviewResultRecord)
    commit_state: CommitState = CommitState.NONE
    commit_sha: str | None = None
    baseline_head: str | None = None
    work_summary: str | None = None
    last_error: str | None = None
    blocked_reason: str | None = None
    changed_paths: list[str] = field(default_factory=list)
    validation_attempt: int = 0
    validation_repair_count: int = 0
    validation_results: list[ValidationCommandResult] = field(default_factory=list)
    provenance_kind: ProvenanceKind | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    updated_at: datetime | None = None
    agent_pid: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        mapping = dict(_require_mapping(data, label="run state"))
        mapping.pop("pre_dirty_fingerprints", None)
        last_transition = mapping.get("last_transition")
        provenance = mapping.get("provenance_kind")
        provenance_kind: ProvenanceKind | None
        if provenance is None:
            provenance_kind = None
        else:
            provenance_kind = ProvenanceKind(_require_str(provenance, label="provenance_kind"))
        return cls(
            schema_version=1,
            item_id=_require_str(mapping["item_id"], label="item_id"),
            logical_attempt=int(mapping.get("logical_attempt", 0)),
            phase=Phase(_require_str(mapping.get("phase", Phase.IDLE.value), label="phase")),
            session_number=int(mapping.get("session_number", 0)),
            session_restart_count=int(mapping.get("session_restart_count", 0)),
            last_transition=(
                Transition(_require_str(last_transition, label="last_transition"))
                if last_transition is not None
                else None
            ),
            review=ReviewResultRecord.from_dict(mapping.get("review")),
            commit_state=CommitState(
                _require_str(mapping.get("commit_state", CommitState.NONE.value), label="commit_state")
            ),
            commit_sha=_optional_str(mapping.get("commit_sha"), label="commit_sha"),
            baseline_head=_optional_str(mapping.get("baseline_head"), label="baseline_head"),
            work_summary=_optional_str(mapping.get("work_summary"), label="work_summary"),
            last_error=_optional_str(mapping.get("last_error"), label="last_error"),
            blocked_reason=_optional_str(
                mapping.get("blocked_reason"), label="blocked_reason"
            ),
            changed_paths=_parse_str_list(mapping.get("changed_paths"), label="changed_paths"),
            validation_attempt=int(mapping.get("validation_attempt", 0)),
            validation_repair_count=int(mapping.get("validation_repair_count", 0)),
            validation_results=[
                ValidationCommandResult.from_dict(entry)
                for entry in mapping.get("validation_results") or []
            ],
            provenance_kind=provenance_kind,
            history=list(mapping.get("history") or []),
            updated_at=_parse_datetime(mapping.get("updated_at"), label="updated_at"),
            agent_pid=(
                int(mapping["agent_pid"])
                if mapping.get("agent_pid") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "logical_attempt": self.logical_attempt,
            "phase": self.phase.value,
            "session_number": self.session_number,
            "session_restart_count": self.session_restart_count,
            "last_transition": (
                self.last_transition.value if self.last_transition is not None else None
            ),
            "review": self.review.to_dict(),
            "commit_state": self.commit_state.value,
            "commit_sha": self.commit_sha,
            "baseline_head": self.baseline_head,
            "work_summary": self.work_summary,
            "last_error": self.last_error,
            "blocked_reason": self.blocked_reason,
            "changed_paths": list(self.changed_paths),
            "validation_attempt": self.validation_attempt,
            "validation_repair_count": self.validation_repair_count,
            "validation_results": [
                entry.to_dict() for entry in self.validation_results
            ],
            "provenance_kind": (
                self.provenance_kind.value if self.provenance_kind is not None else None
            ),
            "history": list(self.history),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at is not None else None
            ),
            "agent_pid": self.agent_pid,
        }

    @classmethod
    def model_validate(cls, data: Any) -> RunState:
        return cls.from_dict(_require_mapping(data, label="run state"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class RestructuringProposal:
    """Structured proposal from a Cursor session for backlog changes."""

    item_id: str
    schema_version: Literal[1] = 1
    supersede: bool = False
    new_items: list[dict[str, Any]] = field(default_factory=list)
    dependency_updates: dict[str, list[str]] = field(default_factory=dict)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestructuringProposal:
        mapping = _require_mapping(data, label="restructure proposal")
        dependency_updates = mapping.get("dependency_updates") or {}
        if not isinstance(dependency_updates, dict):
            raise ValueError("dependency_updates must be a mapping")
        parsed_updates: dict[str, list[str]] = {}
        for key, value in dependency_updates.items():
            parsed_updates[str(key)] = _parse_str_list(value, label=f"dependency_updates[{key}]")
        new_items = mapping.get("new_items") or []
        if not isinstance(new_items, list):
            raise ValueError("new_items must be a list")
        return cls(
            schema_version=1,
            item_id=_require_str(mapping["item_id"], label="item_id"),
            supersede=bool(mapping.get("supersede", False)),
            new_items=[dict(item) for item in new_items if isinstance(item, dict)],
            dependency_updates=parsed_updates,
            notes=_require_str(mapping.get("notes", ""), label="notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "supersede": self.supersede,
            "new_items": list(self.new_items),
            "dependency_updates": {
                key: list(value) for key, value in self.dependency_updates.items()
            },
            "notes": self.notes,
        }

    @classmethod
    def model_validate(cls, data: Any) -> RestructuringProposal:
        return cls.from_dict(_require_mapping(data, label="restructure proposal"))

    def model_dump(self, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        return self.to_dict()

    def model_dump_json(self) -> str:
        import json

        return json.dumps(self.to_dict())


@dataclass
class FinalizeResult:
    commit_sha: str | None
    provenance_kind: ProvenanceKind
    message: str = ""
