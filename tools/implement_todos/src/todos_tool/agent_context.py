"""Agent context configuration: skills and rules referenced in prompts."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

from todos_tool.errors import ValidationError
from todos_tool.paths import resolve_within_repo, validate_relative_path

PhaseName = Literal["implement", "review", "planning", "rendering"]


@dataclass(frozen=True)
class PhaseAgentContext:
    skills: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    model: str | None = None

    @classmethod
    def empty(cls) -> PhaseAgentContext:
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PhaseAgentContext:
        if data is None:
            return cls.empty()
        if not isinstance(data, dict):
            raise ValueError("phase agent_context must be a mapping")
        unknown = set(data) - {"skills", "rules", "model"}
        if unknown:
            raise ValueError(f"Unknown phase agent_context fields: {sorted(unknown)}")
        model = _optional_model(data.get("model"))
        return cls(
            skills=_parse_path_list(data.get("skills"), label="skills"),
            rules=_parse_path_list(data.get("rules"), label="rules"),
            model=model,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.skills:
            payload["skills"] = list(self.skills)
        if self.rules:
            payload["rules"] = list(self.rules)
        if self.model is not None:
            payload["model"] = self.model
        return payload


@dataclass(frozen=True)
class AgentContextConfig:
    default: PhaseAgentContext = field(default_factory=PhaseAgentContext.empty)
    implement: PhaseAgentContext = field(default_factory=PhaseAgentContext.empty)
    review: PhaseAgentContext = field(default_factory=PhaseAgentContext.empty)
    planning: PhaseAgentContext = field(default_factory=PhaseAgentContext.empty)
    rendering: PhaseAgentContext = field(default_factory=PhaseAgentContext.empty)

    @classmethod
    def empty(cls) -> AgentContextConfig:
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AgentContextConfig:
        if data is None:
            return cls.empty()
        if not isinstance(data, dict):
            raise ValueError("agent_context must be a mapping")
        allowed = {f.name for f in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown agent_context fields: {sorted(unknown)}")
        return cls(
            default=PhaseAgentContext.from_dict(data.get("default")),
            implement=PhaseAgentContext.from_dict(data.get("implement")),
            review=PhaseAgentContext.from_dict(data.get("review")),
            planning=PhaseAgentContext.from_dict(data.get("planning")),
            rendering=PhaseAgentContext.from_dict(data.get("rendering")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for name in ("default", "implement", "review", "planning", "rendering"):
            phase = getattr(self, name)
            phase_dict = phase.to_dict()
            if phase_dict:
                payload[name] = phase_dict
        return payload

    def is_empty(self) -> bool:
        for name in ("default", "implement", "review", "planning", "rendering"):
            phase: PhaseAgentContext = getattr(self, name)
            if phase.skills or phase.rules or phase.model is not None:
                return False
        return True

    def phase(self, name: PhaseName) -> PhaseAgentContext:
        return getattr(self, name)


@dataclass(frozen=True)
class ResolvedAgentContext:
    skills: tuple[str, ...]
    rules: tuple[str, ...]


def _parse_path_list(value: Any, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    items: list[str] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{label}[{idx}] must be a non-empty string")
        items.append(validate_relative_path(entry.strip(), label=label))
    return tuple(items)


def _optional_model(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("model must be a string")
    text = value.strip()
    return text or None


def resolve_phase_model(
    phase: PhaseName,
    base_model: str | None,
    *configs: AgentContextConfig | None,
) -> str | None:
    """Resolve the effective model for a phase, with later config layers winning."""
    model = base_model
    for config in configs:
        if config is None or config.is_empty():
            continue
        for source in (config.default, config.phase(phase)):
            if source.model is not None:
                model = source.model
    return model


def resolve_phase_agent_context(
    phase: PhaseName,
    *configs: AgentContextConfig | None,
) -> ResolvedAgentContext:
    """Merge default+phase references from each config in declaration order."""
    skills: list[str] = []
    rules: list[str] = []
    seen_skills: set[str] = set()
    seen_rules: set[str] = set()

    for config in configs:
        if config is None or config.is_empty():
            continue
        for source in (config.default, config.phase(phase)):
            for skill in source.skills:
                if skill not in seen_skills:
                    seen_skills.add(skill)
                    skills.append(skill)
            for rule in source.rules:
                if rule not in seen_rules:
                    seen_rules.add(rule)
                    rules.append(rule)

    return ResolvedAgentContext(skills=tuple(skills), rules=tuple(rules))


def validate_agent_context_paths(
    repo_root: Path,
    resolved: ResolvedAgentContext,
    *,
    label: str,
) -> None:
    errors: list[str] = []
    for path in (*resolved.skills, *resolved.rules):
        try:
            full = resolve_within_repo(repo_root, path)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if not full.is_file():
            errors.append(f"{label}: configured path is not a file: {path}")
    if errors:
        raise ValidationError(errors)
