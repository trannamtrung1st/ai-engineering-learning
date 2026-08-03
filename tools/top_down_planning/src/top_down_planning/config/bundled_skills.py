"""Built-in TDP agent skills injected into every role session by default."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from core_tools.config import SkillEntry
from core_tools.config.errors import ConfigError

AgentRole = Literal["planner", "producer", "reviewer"]

BUNDLED_SKILL_BINDING_PREFIX = "tdp:builtin:"

_ROLE_SKILL_DIRS: dict[AgentRole, str] = {
    "planner": "planner",
    "producer": "producer",
    "reviewer": "reviewer",
}


def bundled_skills_enabled(config: dict[str, Any]) -> bool:
    """Return whether packaged TDP agent skills are auto-injected."""

    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        return True
    value = agent_context.get("bundled_skills")
    if value is None:
        return True
    return bool(value)


def bundled_skills_root() -> Path:
    """Resolve the packaged ``tdp-agent`` skill tree."""

    root = Path(__file__).resolve().parent.parent / "bundled_skills" / "tdp-agent"
    if root.is_dir():
        return root

    raise ConfigError(
        "bundled TDP agent skills are missing from the installed package",
        path="agent_context.bundled_skills",
    )


def bundled_skill_binding_key(path: Path) -> str | None:
    """Return a stable binding key for a packaged skill file, if applicable."""

    root = bundled_skills_root().resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return None
    return f"{BUNDLED_SKILL_BINDING_PREFIX}{relative.as_posix()}"


def _read_skill(skill_path: Path) -> SkillEntry:
    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"failed to read bundled skill file {skill_path}",
            path="agent_context.bundled_skills",
        ) from exc
    if not content.strip():
        raise ConfigError(
            f"bundled skill file is empty: {skill_path}",
            path="agent_context.bundled_skills",
        )
    return SkillEntry(path=skill_path.resolve(), content=content)


def load_bundled_skills_for_role(role: AgentRole) -> tuple[SkillEntry, ...]:
    """Load shared and role-specific packaged skills."""

    root = bundled_skills_root()
    loaded: list[SkillEntry] = []

    shared_skill = root / "SKILL.md"
    if shared_skill.is_file():
        loaded.append(_read_skill(shared_skill))

    role_dir = _ROLE_SKILL_DIRS.get(role)
    if role_dir is not None:
        role_skill = root / role_dir / "SKILL.md"
        if role_skill.is_file():
            loaded.append(_read_skill(role_skill))

    return tuple(loaded)


__all__ = [
    "BUNDLED_SKILL_BINDING_PREFIX",
    "bundled_skill_binding_key",
    "bundled_skills_enabled",
    "bundled_skills_root",
    "load_bundled_skills_for_role",
]
