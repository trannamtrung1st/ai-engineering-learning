"""Load optional repository policy sections from run config YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from todos_tool.agent_context import AgentContextConfig
from todos_tool.context_files import parse_context_file_entry
from todos_tool.errors import TodosToolError
from todos_tool.project_context import (
    AuthorityPolicy,
    ContextFileRef,
    EvidencePolicy,
    GitPolicy,
    ProjectContext,
)


def parse_project_context_from_config(
    raw: dict[str, Any],
    *,
    repo_root: Path,
    source: str = "config",
) -> ProjectContext:
    context_raw = raw.get("context") or {}
    if not isinstance(context_raw, dict):
        raise TodosToolError("context must be a mapping")

    refs: list[ContextFileRef] = []
    seen: set[str] = set()
    for entry in context_raw.get("files") or []:
        ref = parse_context_file_entry(repo_root, entry)
        if ref.path in seen:
            continue
        seen.add(ref.path)
        refs.append(ref)

    instructions_raw = context_raw.get("instructions") or []
    if not isinstance(instructions_raw, list):
        raise TodosToolError("context.instructions must be a list")
    instructions = tuple(
        str(item).strip() for item in instructions_raw if str(item).strip()
    )

    authority_raw = raw.get("authority") or {}
    if not isinstance(authority_raw, dict):
        raise TodosToolError("authority must be a mapping")
    forbidden = tuple(
        str(item).strip()
        for item in (authority_raw.get("forbidden_path_globs") or [])
        if str(item).strip()
    )

    evidence_raw = raw.get("evidence") or {}
    if not isinstance(evidence_raw, dict):
        raise TodosToolError("evidence must be a mapping")
    required_commands = tuple(
        str(item).strip()
        for item in (evidence_raw.get("required_commands") or [])
        if str(item).strip()
    )
    forbidden_patterns = tuple(
        str(item).strip()
        for item in (evidence_raw.get("forbidden_command_patterns") or [])
        if str(item).strip()
    )

    git_raw = raw.get("git") or {}
    if not isinstance(git_raw, dict):
        raise TodosToolError("git must be a mapping")
    commit_prefix = str(git_raw.get("commit_prefix", "agent:")).strip() or "agent:"

    return ProjectContext(
        context_files=tuple(refs),
        instructions=instructions,
        authority=AuthorityPolicy(forbidden_path_globs=forbidden),
        evidence=EvidencePolicy(
            required_commands=required_commands,
            forbidden_command_patterns=forbidden_patterns,
        ),
        git=GitPolicy(commit_prefix=commit_prefix),
        source=source,
    )


def parse_agent_context_from_config(raw: dict[str, Any]) -> AgentContextConfig | None:
    agent_raw = raw.get("agent_context")
    if agent_raw is None:
        return None
    try:
        config = AgentContextConfig.from_dict(agent_raw)
    except ValueError as exc:
        raise TodosToolError(f"Invalid agent_context: {exc}") from exc
    if config.is_empty():
        return None
    return config


def merge_project_context(
    base: ProjectContext,
    *,
    extra_context_files: tuple[ContextFileRef, ...] = (),
    cli_git_commit_prefix: str | None = None,
) -> ProjectContext:
    ctx = base
    if extra_context_files:
        ctx = ctx.with_extra_context_files(extra_context_files)
    if cli_git_commit_prefix is not None:
        ctx = ctx.with_git_prefix(cli_git_commit_prefix.strip() or "agent:")
    return ctx
