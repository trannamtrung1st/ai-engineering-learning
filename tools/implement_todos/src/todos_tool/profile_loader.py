"""Load optional repository profiles and CLI context overrides."""

from __future__ import annotations

from pathlib import Path

import yaml

from todos_tool.errors import ValidationError
from todos_tool.paths import resolve_within_repo, validate_relative_path
from todos_tool.project_context import (
    AuthorityPolicy,
    ContextFileRef,
    EvidencePolicy,
    GitPolicy,
    ProjectContext,
    ResolvedContextFile,
)

DEFAULT_PROFILE_NAME = ".implement-todos.yaml"
SUPPORTED_SCHEMA_VERSION = 1


def discover_profile_path(repo_root: Path) -> Path | None:
    candidate = repo_root / DEFAULT_PROFILE_NAME
    return candidate if candidate.is_file() else None


def load_project_context(
    repo_root: Path,
    *,
    profile_path: Path | None = None,
    extra_context_files: tuple[str, ...] = (),
    cli_git_commit_prefix: str | None = None,
) -> ProjectContext:
    ctx = ProjectContext.neutral()
    selected = profile_path or discover_profile_path(repo_root)
    if selected is not None:
        ctx = _load_profile(repo_root, selected)
    extra_refs = tuple(
        ContextFileRef(path=_resolve_context_path(repo_root, path), required=False)
        for path in extra_context_files
    )
    ctx = ctx.with_extra_context_files(extra_refs)
    if cli_git_commit_prefix is not None:
        ctx = ctx.with_git_prefix(cli_git_commit_prefix.strip() or "agent:")
    return ctx


def resolve_context_files(
    repo_root: Path,
    refs: tuple[ContextFileRef, ...],
) -> list[ResolvedContextFile]:
    resolved: list[ResolvedContextFile] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.path in seen:
            continue
        seen.add(ref.path)
        full = repo_root / ref.path
        resolved.append(
            ResolvedContextFile(
                path=ref.path,
                required=ref.required,
                exists=full.is_file(),
            )
        )
    return resolved


def validate_required_context(files: list[ResolvedContextFile]) -> None:
    missing = [entry.path for entry in files if entry.required and not entry.exists]
    if missing:
        raise ValidationError(
            [f"Required context file missing: {path}" for path in missing]
        )


def _resolve_context_path(repo_root: Path, path: str) -> str:
    rel = validate_relative_path(path, label="context file")
    resolve_within_repo(repo_root, rel)
    return rel


def _load_profile(repo_root: Path, profile_path: Path) -> ProjectContext:
    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError([f"Cannot read profile {profile_path}: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise ValidationError([f"Invalid YAML in profile {profile_path}: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ValidationError([f"Profile must be a mapping: {profile_path}"])

    version = data.get("schema_version", 1)
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ValidationError(
            [f"Unsupported profile schema_version {version!r} in {profile_path}"]
        )

    context = data.get("context") or {}
    files_raw = context.get("files") or []
    refs: list[ContextFileRef] = []
    seen: set[str] = set()
    for entry in files_raw:
        if isinstance(entry, str):
            rel = _resolve_context_path(repo_root, entry)
            required = False
        elif isinstance(entry, dict):
            raw_path = entry.get("path")
            if not isinstance(raw_path, str):
                raise ValidationError(["Profile context file entry missing path"])
            rel = _resolve_context_path(repo_root, raw_path)
            required = bool(entry.get("required", False))
        else:
            raise ValidationError(["Profile context files must be strings or mappings"])
        if rel in seen:
            continue
        seen.add(rel)
        refs.append(ContextFileRef(path=rel, required=required))

    instructions_raw = context.get("instructions") or []
    instructions = tuple(str(item).strip() for item in instructions_raw if str(item).strip())

    authority_raw = data.get("authority") or {}
    forbidden = tuple(
        str(item).strip()
        for item in (authority_raw.get("forbidden_path_globs") or [])
        if str(item).strip()
    )

    evidence_raw = data.get("evidence") or {}
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

    git_raw = data.get("git") or {}
    commit_prefix = str(git_raw.get("commit_prefix", "agent:")).strip() or "agent:"

    return ProjectContext(
        schema_version=version,
        context_files=tuple(refs),
        instructions=instructions,
        authority=AuthorityPolicy(forbidden_path_globs=forbidden),
        evidence=EvidencePolicy(
            required_commands=required_commands,
            forbidden_command_patterns=forbidden_patterns,
        ),
        git=GitPolicy(commit_prefix=commit_prefix),
        source="profile",
    )
