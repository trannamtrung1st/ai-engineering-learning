"""Resolve and validate repository context file references."""

from __future__ import annotations

from pathlib import Path

from todos_tool.errors import ValidationError
from todos_tool.paths import resolve_within_repo, validate_relative_path
from todos_tool.project_context import ContextFileRef, ResolvedContextFile


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


def parse_context_file_entry(repo_root: Path, entry: object) -> ContextFileRef:
    if isinstance(entry, str):
        rel = _resolve_context_path(repo_root, entry)
        return ContextFileRef(path=rel, required=False)
    if isinstance(entry, dict):
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise ValidationError(["Context file entry missing path"])
        rel = _resolve_context_path(repo_root, raw_path)
        return ContextFileRef(path=rel, required=bool(entry.get("required", False)))
    raise ValidationError(["Context files must be strings or mappings"])


def _resolve_context_path(repo_root: Path, path: str) -> str:
    rel = validate_relative_path(path, label="context file")
    resolve_within_repo(repo_root, rel)
    return rel
